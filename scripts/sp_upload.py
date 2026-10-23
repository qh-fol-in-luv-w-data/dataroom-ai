"""Upload the demo data room to a real SharePoint site with your own Microsoft 365 account.

- Sign-in: device code. You sign in yourself in the browser (MFA as your tenant requires);
  this script never sees your password. The refresh token is cached in data/.sp_token.json
  (git-ignored) so a re-run resumes without signing in again.
- Upload: every file keeps its folder (COMMON/…, GRP-A/…, INTERNAL/…) in the site's
  document library; files > 4 MB use an upload session. Re-runs skip files already uploaded.
- AI_Use: a choice column (Allowed / OnPremOnly / Excluded) is created on the library and set
  per file, as the plan's data-room owner would.
- Never uploaded: the simulated malware sample and the encrypted file (Defender would flag
  them); they stay simulated in the demo.
- Writes data/tenant/sharepoint_links.json (item_id → webUrl); the demo's
  "Mở trên SharePoint" then opens the real file.

Needs an app registration in your tenant (no admin consent): public client flows enabled,
delegated permissions Files.ReadWrite.All, Sites.ReadWrite.All and Sites.Manage.All
(Manage: create the library and the AI_Use column).
Usage:
  .venv/bin/python scripts/sp_upload.py --tenant <tenant id or domain> --client-id <app id> \\
      --site https://<tenant>.sharepoint.com/sites/<site> [--library "DataRoom AI Demo"] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from dr.m365.graph import Graph, GraphError  # noqa: E402

TEN = ROOT / "data" / "tenant"
LINKS = TEN / "sharepoint_links.json"
CACHE = ROOT / "data" / ".sp_token.json"
SCOPES = "Files.ReadWrite.All Sites.ReadWrite.All Sites.Manage.All offline_access"
CHOICES = ["Allowed", "OnPremOnly", "Excluded"]
SMALL = 4 * 1024 * 1024
_token_lock = __import__("threading").RLock()


class DeviceLogin:
    def __init__(self, tenant: str, client_id: str, http: httpx.Client, cache: Path = CACHE):
        self.base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
        self.client_id, self.http, self.cache = client_id, http, cache
        self.access, self.exp, self.refresh = None, 0.0, None
        if cache.exists():
            d = json.loads(cache.read_text())
            if d.get("client_id") == client_id:
                self.refresh = d.get("refresh_token")

    def _store(self, d: dict) -> None:
        self.access, self.exp = d["access_token"], time.time() + int(d.get("expires_in", 3600))
        self.refresh = d.get("refresh_token", self.refresh)
        self.cache.write_text(json.dumps({"client_id": self.client_id, "refresh_token": self.refresh}))
        self.cache.chmod(0o600)

    def token(self) -> str:
        with _token_lock:              # parallel uploads: one refresh, not eight
            return self._token()

    def _token(self) -> str:
        if self.access and self.exp - 120 > time.time():
            return self.access
        if self.refresh:
            r = self.http.post(f"{self.base}/token", data={"client_id": self.client_id, "grant_type": "refresh_token",
                                                           "refresh_token": self.refresh, "scope": SCOPES})
            if r.status_code == 200:
                self._store(r.json())
                return self.access
        d = self.http.post(f"{self.base}/devicecode", data={"client_id": self.client_id, "scope": SCOPES}).json()
        if "device_code" not in d:
            raise SystemExit(f"Không bắt đầu đăng nhập được: {d.get('error_description', d)}")
        print("\n" + d["message"] + "\n", flush=True)
        deadline = time.time() + int(d.get("expires_in", 900))
        while time.time() < deadline:
            time.sleep(int(d.get("interval", 5)))
            r = self.http.post(f"{self.base}/token", data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": self.client_id, "device_code": d["device_code"]}).json()
            if "access_token" in r:
                self._store(r)
                return self.access
            if r.get("error") not in ("authorization_pending", "slow_down"):
                raise SystemExit(f"Đăng nhập thất bại: {r.get('error_description', r)}")
        raise SystemExit("Hết thời gian đăng nhập")


def site_and_drive(g: Graph, site_url: str, library: str | None = None) -> tuple[str, str, str, str]:
    """The site's default document library, or the library named `library` (created if missing:
    lets you use a separate library on a site you already own when you cannot create sites)."""
    u = urlparse(site_url)
    site = g.get(f"sites/{u.netloc}:{u.path.rstrip('/')}")
    if not library:
        drive = g.get(f"sites/{site['id']}/drive")
        lst = g.get(f"sites/{site['id']}/drive/list", params={"$select": "id,displayName"})
        return site["id"], drive["id"], lst["id"], ""
    lists = [x for x in g.pages(f"sites/{site['id']}/lists", params={"$select": "id,displayName,list"})
             if x.get("displayName") == library]
    if lists:
        lst = lists[0]
    else:
        r = g.request("POST", f"sites/{site['id']}/lists",
                      json={"displayName": library, "list": {"template": "documentLibrary"}})
        if r.status_code == 403:
            print(f"  ! Không được tạo thư viện '{library}' (403): dùng thư mục '{library}/' trong thư viện mặc định")
            drive = g.get(f"sites/{site['id']}/drive")
            lst = g.get(f"sites/{site['id']}/drive/list", params={"$select": "id"})
            return site["id"], drive["id"], lst["id"], f"{library}/"
        if r.status_code not in (200, 201):
            raise GraphError(r.status_code, r.text, f"create library {library}")
        lst = r.json()
    drive = g.get(f"sites/{site['id']}/lists/{lst['id']}/drive")
    return site["id"], drive["id"], lst["id"], ""


def ensure_ai_use_column(g: Graph, site_id: str, list_id: str) -> bool:
    cols = [c["name"] for c in g.pages(f"sites/{site_id}/lists/{list_id}/columns", params={"$select": "name"})]
    if "AI_Use" in cols:
        return True
    r = g.request("POST", f"sites/{site_id}/lists/{list_id}/columns", json={
        "name": "AI_Use", "displayName": "AI_Use", "description": "Cho phép AI core dùng file này",
        "choice": {"allowTextEntry": False, "choices": CHOICES, "displayAs": "dropDownMenu"},
        "defaultValue": {"value": "Excluded"}})
    if r.status_code == 403:
        print("  ! Không được tạo cột AI_Use (403, thiếu Sites.Manage.All): vẫn tải file, AI_Use giữ ở AI core")
        return False
    if r.status_code not in (200, 201):
        raise GraphError(r.status_code, r.text, "create AI_Use column")
    return True


def upload(g: Graph, drive_id: str, rel: str, data: bytes) -> dict:
    path = quote(rel)
    if len(data) <= SMALL:
        r = g.request("PUT", f"drives/{drive_id}/root:/{path}:/content", content=data,
                      headers={"Content-Type": "application/octet-stream"})
        if r.status_code not in (200, 201):
            raise GraphError(r.status_code, r.text, rel)
        return r.json()
    s = g.request("POST", f"drives/{drive_id}/root:/{path}:/createUploadSession",
                  json={"item": {"@microsoft.graph.conflictBehavior": "replace"}})
    if s.status_code != 200:
        raise GraphError(s.status_code, s.text, rel)
    url, chunk, out = s.json()["uploadUrl"], 5 * 1024 * 1024, None
    for i in range(0, len(data), chunk):
        part = data[i:i + chunk]
        r = g.http.put(url, content=part, headers={
            "Content-Range": f"bytes {i}-{i + len(part) - 1}/{len(data)}", "Content-Length": str(len(part))})
        if r.status_code not in (200, 201, 202):
            raise GraphError(r.status_code, r.text, rel)
        out = r.json()
    return out


def _retry(fn, what: str, tries: int = 8):
    """Graph throttles bulk uploads (429/503 with Retry-After); network blips happen on long runs."""
    r = None
    for i in range(tries):
        try:
            r = fn()
        except httpx.HTTPError:
            if i == tries - 1:
                raise
            time.sleep(min(5 * 2 ** i, 120))
            continue
        if r.status_code in (429, 503, 504) and i < tries - 1:
            time.sleep(int(r.headers.get("Retry-After") or min(5 * 2 ** i, 120)))
            continue
        return r
    raise GraphError(r.status_code if r is not None else 0, r.text if r is not None else "", what)


def upload_file(g: Graph, drive_id: str, rel: str, path: Path) -> dict:
    """Like upload(), from disk: big files go up 10 MB at a time without being read whole."""
    size = path.stat().st_size
    if size <= SMALL:
        data = path.read_bytes()
        r = _retry(lambda: g.request("PUT", f"drives/{drive_id}/root:/{quote(rel)}:/content", content=data,
                                     headers={"Content-Type": "application/octet-stream"}), rel)
        if r.status_code not in (200, 201):
            raise GraphError(r.status_code, r.text, rel)
        return r.json()
    s = _retry(lambda: g.request("POST", f"drives/{drive_id}/root:/{quote(rel)}:/createUploadSession",
                                 json={"item": {"@microsoft.graph.conflictBehavior": "replace"}}), rel)
    if s.status_code != 200:
        raise GraphError(s.status_code, s.text, rel)
    url, chunk, out = s.json()["uploadUrl"], 10 * 1024 * 1024, None   # multiple of 320 KiB
    with open(path, "rb") as fh:
        for i in range(0, size, chunk):
            part = fh.read(chunk)
            r = _retry(lambda: g.http.put(url, content=part, headers={
                "Content-Range": f"bytes {i}-{i + len(part) - 1}/{size}", "Content-Length": str(len(part))}), rel)
            if r.status_code not in (200, 201, 202):
                raise GraphError(r.status_code, r.text, rel)
            out = r.json()
    return out


def show_library(g: Graph, drive_id: str) -> None:
    top = list(g.pages(f"drives/{drive_id}/root/children", params={"$select": "id,name,size,folder,file"}))
    for x in top:
        cnt = x.get("folder", {}).get("childCount")
        print(f"  {'[thư mục]' if 'folder' in x else '[file]'} {x['name']}  {x.get('size', 0) / 2**20:,.1f} MB"
              + (f"  ({cnt} mục con)" if cnt is not None else ""))
    print(f"{len(top)} mục ở cấp đầu, tổng {sum(x.get('size', 0) for x in top) / 2**20:,.0f} MB")


def wipe_library(g: Graph, drive_id: str) -> int:
    """Delete every top-level item; deleted items go to the site recycle bin (restorable 93 days)."""
    n = 0
    for x in list(g.pages(f"drives/{drive_id}/root/children", params={"$select": "id,name"})):
        r = _retry(lambda: g.request("DELETE", f"drives/{drive_id}/items/{x['id']}"), x["name"])
        if r.status_code not in (200, 204):
            raise GraphError(r.status_code, r.text, f"delete {x['name']}")
        n += 1
        print(f"  đã xóa {x['name']}", flush=True)
    return n


MAX_PATH = 400      # SharePoint: the decoded path of a file, from /sites/... to the extension


def shorten(rel: str, limit: int) -> str:
    """A path within the limit. Paths already within it are unchanged; otherwise folder names longer
    than 30 characters are cut to 28 + '~' (deepest first), then to 16 + '~', and only if that is
    not enough the end of the file name is cut (its extension kept)."""
    parts = rel.split("/")
    for keep in (28, 16):
        for i in sorted(range(len(parts) - 1), key=lambda k: -k):
            if len("/".join(parts)) <= limit:
                return "/".join(parts)
            if len(parts[i]) > keep + 2:
                parts[i] = parts[i][:keep].rstrip(". ") + "~"
    over = len("/".join(parts)) - limit
    if over > 0:
        stem, dot, ext = parts[-1].rpartition(".")
        stem = stem if dot else parts[-1]
        parts[-1] = stem[:max(8, len(stem) - over - 1)].rstrip(". ") + "~" + (dot + ext if dot else "")
    return "/".join(parts)


def upload_tree(g: Graph, drive_id: str, src: Path, prefix: str = "", workers: int = 8,
                site_path: str = "") -> int:
    """Upload every file under src keeping its folders, several at a time: most files are small, so one
    at a time is bound by the request round trip (~1 MB/s), not bandwidth. Progress is kept in
    src/_sp_uploaded.json, so a re-run only sends what is missing; a failed file is retried next run."""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    state_f = src / "_sp_uploaded.json"
    state = json.loads(state_f.read_text(encoding="utf-8")) if state_f.exists() else {}
    files = sorted(p for p in src.rglob("*") if p.is_file() and p.name != ".DS_Store"
                   and not (p.parent == src and p.name.startswith("_")))
    todo = [p for p in files if state.get(p.relative_to(src).as_posix()) != p.stat().st_size]
    print(f"{len(files)} file ({sum(p.stat().st_size for p in files) / 2**30:.1f} GB), đã có {len(files) - len(todo)}, "
          f"còn {len(todo)} ({sum(p.stat().st_size for p in todo) / 2**30:.1f} GB) · {workers} luồng", flush=True)
    lock = threading.Lock()
    done, sent, failed, t0 = 0, 0, [], time.time()

    def one(p: Path) -> tuple[str, int]:
        rel = p.relative_to(src).as_posix()
        # SharePoint refuses " * : < > ? \\ | in names and names ending with a dot or space
        safe = "/".join(re.sub(r'["*:<>?\\|]', "_", part).rstrip(". ") or "_" for part in rel.split("/"))
        upload_file(g, drive_id, f"{prefix}{shorten(safe, MAX_PATH - len(site_path) - len(prefix))}", p)
        return rel, p.stat().st_size

    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(one, p): p for p in todo}
        for f in as_completed(futs):
            try:
                rel, size = f.result()
            except Exception as e:
                failed.append(futs[f].relative_to(src).as_posix())
                print(f"  LỖI {futs[f].name}: {str(e)[:200]}", flush=True)
                continue
            with lock:
                state[rel] = size
                done, sent = done + 1, sent + size
                if done % 50 == 0:
                    state_f.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
                    el = max(time.time() - t0, 1)
                    print(f"  {len(files) - len(todo) + done}/{len(files)}  ·  {sent / 2**30:.2f} GB  ·  "
                          f"{sent / el / 2**20:.1f} MB/s  ·  {done / el * 60:.0f} file/phút", flush=True)
    state_f.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"Xong: tải mới {done} file, {len(state)}/{len(files)} file đã có trên SharePoint"
          + (f", lỗi {len(failed)} (chạy lại lệnh để thử lại)" if failed else ""))
    return done


def main(argv=None, http: httpx.Client | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", help="tenant id or domain (default: tenant_id of --m365-config)")
    ap.add_argument("--client-id", help="app id (default: the one the cached sign-in in --token-cache was made with)")
    ap.add_argument("--m365-config", default=str(ROOT / "data" / "m365.json"))
    ap.add_argument("--site", help="https://<tenant>.sharepoint.com/sites/<site>")
    ap.add_argument("--list-sites", action="store_true", help="sign in and list the sites you can use")
    ap.add_argument("--library", help="upload into this document library (created if missing) instead of the default one")
    ap.add_argument("--links", action="store_true",
                    help="list every sharing link on the site's libraries (folders and files)")
    ap.add_argument("--revoke-links", action="store_true",
                    help="delete anonymous ('Anyone') and organisation-wide links found by --links "
                         "(specific-people links and normal permissions are kept); needs --yes")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--show", action="store_true", help="list what the library holds now")
    ap.add_argument("--wipe", action="store_true", help="delete everything in the library (recycle bin); needs --yes")
    ap.add_argument("--src", help="upload this folder tree instead of the demo tenant (e.g. 'data/AI Data Room')")
    ap.add_argument("--token-cache", default=str(CACHE), help="where the sign-in refresh token is cached")
    ap.add_argument("--workers", type=int, default=8, help="parallel uploads for --src")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    # ids from the local config / cached sign-in, so the command line carries none
    if not a.tenant and Path(a.m365_config).exists():
        a.tenant = json.loads(Path(a.m365_config).read_text(encoding="utf-8")).get("tenant_id")
    if not a.client_id and Path(a.token_cache).exists():
        a.client_id = json.loads(Path(a.token_cache).read_text()).get("client_id")
    if not a.tenant or not a.client_id:
        ap.error("--tenant and --client-id are required (no m365 config / cached sign-in found)")
    if a.list_sites:
        http = http or httpx.Client(timeout=60, follow_redirects=True)
        g = Graph(DeviceLogin(a.tenant, a.client_id, http).token, http)
        seen = {}
        for path in ("me/followedSites", "sites?search=*&$top=50"):
            try:
                for x in g.pages(path):
                    seen.setdefault(x.get("webUrl"), x.get("displayName") or x.get("name"))
            except GraphError as e:
                print(f"  ({path}: {e.status})")
        print(f"\n{len(seen)} site:")
        for url, name in sorted(seen.items(), key=lambda kv: str(kv[1])):
            print(f"  {name}  →  {url}")
        return 0
    if not a.site:
        ap.error("--site is required (or use --list-sites)")
    if a.links or a.revoke_links:
        if a.revoke_links and not a.yes:
            ap.error("--revoke-links deletes sharing links on the real tenant: add --yes")
        http = http or httpx.Client(timeout=60, follow_redirects=True)
        g = Graph(DeviceLogin(a.tenant, a.client_id, http).token, http)
        found = sharing_links(g, a.site, revoke=a.revoke_links, library=a.library)
        if a.revoke_links and SHARES.exists():
            SHARES.unlink()                      # the local copy of the (now dead) public URLs
        return 0 if not a.revoke_links or all(f["revoked"] for f in found if f["broad"]) else 1
    if a.show or a.wipe or a.src:
        if a.wipe and not a.yes:
            ap.error("--wipe deletes the library's content on the real tenant: add --yes")
        http = http or httpx.Client(timeout=300, follow_redirects=True)
        g = Graph(DeviceLogin(a.tenant, a.client_id, http, Path(a.token_cache)).token, http)
        _, drive_id, _, prefix = site_and_drive(g, a.site, a.library)
        print(f"Thư viện: {a.library or '(mặc định)'} trên {a.site}")
        show_library(g, drive_id)
        if a.wipe:
            print(f"Đã xóa {wipe_library(g, drive_id)} mục (vào thùng rác của site)")
        if a.src:
            lib_url = g.get(f"drives/{drive_id}", params={"$select": "webUrl"})["webUrl"]
            site_path = unquote(urlparse(lib_url).path).rstrip("/") + "/"     # /sites/DSA/DataRoom AI Demo/
            upload_tree(g, drive_id, Path(a.src), prefix, a.workers, site_path)
        return 0
    t = json.loads((TEN / "tenant.json").read_text(encoding="utf-8"))
    items = [i for i in t["items"] if not i.get("malware") and not i.get("encrypted")]
    skipped = [i["name"] for i in t["items"] if i.get("malware") or i.get("encrypted")]
    total = sum((TEN / "files" / i["file"]).stat().st_size for i in items)
    print(f"{len(items)} file ({total / 2**20:.0f} MB) → {a.site}; không tải: {skipped}")
    if a.dry_run:
        return 0
    http = http or httpx.Client(timeout=120, follow_redirects=True)
    login = DeviceLogin(a.tenant, a.client_id, http)
    g = Graph(login.token, http)
    site_id, drive_id, list_id, prefix = site_and_drive(g, a.site, a.library)
    has_col = ensure_ai_use_column(g, site_id, list_id)
    links = json.loads(LINKS.read_text()) if LINKS.exists() else {}
    done = 0
    for n, it in enumerate(items, 1):
        data = (TEN / "files" / it["file"]).read_bytes()
        prev = links.get(it["id"])
        if prev and prev.get("size") == len(data) and prev.get("site") == a.site:
            continue
        rel = f"{prefix}{it['site']}/{it['path']}/{it['name']}".replace("//", "/")
        di = upload(g, drive_id, rel, data)
        if has_col:
            r = g.request("PATCH", f"drives/{drive_id}/items/{di['id']}/listItem/fields",
                          json={"AI_Use": it.get("ai_use") or "Excluded"})
            if r.status_code != 200:
                raise GraphError(r.status_code, r.text, f"AI_Use {rel}")
        links[it["id"]] = {"web_url": di["webUrl"], "drive_item_id": di["id"], "size": len(data), "site": a.site}
        done += 1
        if done % 25 == 0:
            LINKS.write_text(json.dumps(links, ensure_ascii=False, indent=1))
            print(f"  {n}/{len(items)}", flush=True)
    LINKS.write_text(json.dumps(links, ensure_ascii=False, indent=1))
    print(f"Xong: tải mới {done}, tổng {len(links)} file có link SharePoint → {LINKS}")
    return 0


SHARES = TEN / "sharepoint_share_links.json"


def sharing_links(g: Graph, site_url: str, revoke: bool = False, library: str | None = None) -> list[dict]:
    """Every sharing link on every document library of the site, folders and files alike.
    'Broad' links (anonymous = anyone with the URL, organization = anyone in the tenant) are the
    ones a Data Room must not have: access has to come from the account's own permissions, checked
    by SharePoint at sign-in. With revoke=True those are deleted; specific-people links are kept.
    Link URLs are never printed (an anonymous URL is itself the key)."""
    host, path = re.match(r"https://([^/]+)(/sites/[^/?#]+)", site_url).groups()
    site_id = g.request("GET", f"sites/{host}:{path}").json()["id"]
    out = []
    seen: set[str] = set()
    for d in g.pages(f"sites/{site_id}/drives"):
        if library and d["name"] != library:
            continue
        stack = [("root", "", True)]
        while stack:
            ref, rel, is_folder = stack.pop()
            item_path = f"drives/{d['id']}/items/{ref}" if ref != "root" else f"drives/{d['id']}/root"
            r = g.request("GET", f"{item_path}/permissions")
            perms = r.json().get("value", []) if r.status_code == 200 else []
            for pm in perms:
                link = pm.get("link")
                key = pm.get("shareId") or link.get("webUrl") or pm["id"]
                if not link or pm.get("inheritedFrom") or key in seen:
                    continue                     # a child shows its parent's link too: count it once
                seen.add(key)                    # (parents are visited first: the highest folder is kept)
                scope = link.get("scope")
                rec = {"library": d["name"], "path": rel or "/", "scope": scope, "type": link.get("type"),
                       "expires": pm.get("expirationDateTime"), "broad": scope in ("anonymous", "organization"),
                       "revoked": False}
                if revoke and rec["broad"]:
                    rr = g.request("DELETE", f"{item_path}/permissions/{pm['id']}")
                    rec["revoked"] = rr.status_code in (200, 204)
                out.append(rec)
                print(f"  {'THU HỒI ' if rec['revoked'] else ''}{rec['library']}/{rec['path']}  scope={scope} "
                      f"type={rec['type']} hết hạn={rec['expires'] or 'không'}", flush=True)
            if is_folder:
                for ch in g.pages(f"{item_path}/children"):
                    stack.append((ch["id"], f"{rel}/{ch['name']}".lstrip("/"), "folder" in ch))
    broad = [f for f in out if f["broad"]]
    print(f"\n{len(out)} link chia sẻ, {len(broad)} link rộng (anyone/organization)"
          + (f", đã thu hồi {sum(f['revoked'] for f in broad)}" if revoke else ""))
    return out


if __name__ == "__main__":
    sys.exit(main())
