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
delegated permissions Files.ReadWrite.All + Sites.ReadWrite.All (user consent).
Usage:
  .venv/bin/python scripts/sp_upload.py --tenant <tenant id or domain> --client-id <app id> \\
      --site https://<tenant>.sharepoint.com/sites/<site> [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from dr.m365.graph import Graph, GraphError  # noqa: E402

TEN = ROOT / "data" / "tenant"
LINKS = TEN / "sharepoint_links.json"
CACHE = ROOT / "data" / ".sp_token.json"
SCOPES = "Files.ReadWrite.All Sites.ReadWrite.All offline_access"
CHOICES = ["Allowed", "OnPremOnly", "Excluded"]
SMALL = 4 * 1024 * 1024


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


def site_and_drive(g: Graph, site_url: str) -> tuple[str, str, str]:
    u = urlparse(site_url)
    site = g.get(f"sites/{u.netloc}:{u.path.rstrip('/')}")
    drive = g.get(f"sites/{site['id']}/drive")
    lst = g.get(f"sites/{site['id']}/drive/list", params={"$select": "id,displayName"})
    return site["id"], drive["id"], lst["id"]


def ensure_ai_use_column(g: Graph, site_id: str, list_id: str) -> None:
    cols = [c["name"] for c in g.pages(f"sites/{site_id}/lists/{list_id}/columns", params={"$select": "name"})]
    if "AI_Use" in cols:
        return
    r = g.request("POST", f"sites/{site_id}/lists/{list_id}/columns", json={
        "name": "AI_Use", "displayName": "AI_Use", "description": "Cho phép AI core dùng file này",
        "choice": {"allowTextEntry": False, "choices": CHOICES, "displayAs": "dropDownMenu"},
        "defaultValue": {"value": "Excluded"}})
    if r.status_code not in (200, 201):
        raise GraphError(r.status_code, r.text, "create AI_Use column")


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


def main(argv=None, http: httpx.Client | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--site", required=True, help="https://<tenant>.sharepoint.com/sites/<site>")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
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
    site_id, drive_id, list_id = site_and_drive(g, a.site)
    ensure_ai_use_column(g, site_id, list_id)
    links = json.loads(LINKS.read_text()) if LINKS.exists() else {}
    done = 0
    for n, it in enumerate(items, 1):
        data = (TEN / "files" / it["file"]).read_bytes()
        prev = links.get(it["id"])
        if prev and prev.get("size") == len(data) and prev.get("site") == a.site:
            continue
        rel = f"{it['site']}/{it['path']}/{it['name']}".replace("//", "/")
        di = upload(g, drive_id, rel, data)
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


if __name__ == "__main__":
    sys.exit(main())
