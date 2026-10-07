"""The nine Microsoft 365 integration tests (master plan §9.1) against a real test site.

Runs what can be automated, measures what must be measured, and prints a checklist for the
infrastructure-only tests. Writes logs/m365_probe-<time>.json and a Markdown summary.

  .venv/bin/python scripts/m365_probe.py --example-config      # template for data/m365.json
  .venv/bin/python scripts/m365_probe.py                         # automated tests 1, 2, 5, 8
  .venv/bin/python scripts/m365_probe.py --user                  # + test 3 (OBO): a test user signs in
  .venv/bin/python scripts/m365_probe.py --user --measure-x ITEM # + revocation latency X

Nothing is written to the tenant. Secrets/certificates are read from the config file paths;
the user sign-in for test 3 happens in the person's own browser (device code), the script
never sees a password.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from dr.config import settings  # noqa: E402
from dr.ingest import safety  # noqa: E402
from dr.m365.auth import AuthError, jwt_claims  # noqa: E402
from dr.m365.graph import GraphError  # noqa: E402
from dr.m365.tenant import DELTA_PREFER, USER_TOKEN, GraphTenant, item_key  # noqa: E402

EXAMPLE = {
    "tenant_id": "<GUID tenant>",
    "sharepoint_host": "<tenant>.sharepoint.com",
    "reader": {"client_id": "<content-reader + acl-reader app: Sites.Selected (Graph + SharePoint), read>",
               "cert_path": "/secure/path/reader.pem"},
    "directory": {"client_id": "<directory-reader app: GroupMember.Read.All, User.Read.All, Application.Read.All>",
                  "cert_path": "/secure/path/directory.pem"},
    "api": {"client_id": "<dataroom-ai-api app: exposes scope Chat.Use; delegated Files.Read (OBO)>",
            "cert_path": "/secure/path/api.pem"},
    "spa_client_id": "<SPA app registration used by the browser (MSAL)>",
    "probe_public_client_id": "<optional: public client with device-code flow, for test 3>",
    "ai_app_sp_id": "<object id of the dataroom-ai-api service principal>",
    "app_roles": {"<appRoleId of Investor.AI>": "Investor.AI",
                  "<appRoleId of Investor.AI.Summarize>": "Investor.AI.Summarize",
                  "<appRoleId of Staff.AI>": "Staff.AI", "<appRoleId of Reviewer>": "Reviewer",
                  "<appRoleId of DataRoom.AIAdmin>": "DataRoom.AIAdmin"},
    "admin_role": "DataRoom.AIAdmin",
    "groups": {"<entra group id of DR-INV-A>": "DR-INV-A", "<entra group id of DR-INV-B>": "DR-INV-B",
               "<entra group id of DR-STAFF>": "DR-STAFF"},
    "sites": [{"key": "COMMON", "name": "Data Room – Chung", "site_id": "<host>,<site guid>,<web guid>",
               "url": "https://<tenant>.sharepoint.com/sites/<site>", "rac_groups": []}],
    "ai_use_field": "AI_Use",
    "sp_group_lag_seconds": 3600,
    "entra_interval_seconds": 60,
}

R: dict[str, dict] = {}


def record(n: int, name: str, status: str, **detail) -> None:
    R[str(n)] = {"test": name, "status": status, **detail}
    mark = {"PASS": "✓", "FAIL": "✗", "WARN": "!", "MANUAL": "…", "SKIP": "-"}[status]
    print(f"{mark} {n}. {name}: {status} {json.dumps(detail, ensure_ascii=False)[:300]}", flush=True)


def first_file(t: GraphTenant) -> tuple[str, str, str, dict] | None:
    for key in t.sites:
        for d in t._site_drives(key):
            for it in t.graph.pages(f"drives/{d}/root/children"):
                stack = [it]
                while stack:
                    x = stack.pop()
                    if "file" in x:
                        return key, d, x["id"], x
                    if "folder" in x:
                        stack += list(t.graph.pages(f"drives/{d}/items/{x['id']}/children"))
    return None


def test1(t: GraphTenant) -> tuple | None:
    """Sites.Selected read: delta, versions, content, format=pdf, list item fields."""
    detail = {}
    try:
        for key in t.sites:
            for d in t._site_drives(key):
                items, link = t.graph.delta(f"drives/{d}/root/delta", headers=DELTA_PREFER)
                detail[f"delta:{key}"] = len(items)
        f = first_file(t)
        if not f:
            record(1, "Sites.Selected: delta, versions, content, format=pdf, AI_Use", "WARN", note="site trống", **detail)
            return None
        key, d, gid, x = f
        detail["versions"] = len(list(t.graph.pages(f"drives/{d}/items/{gid}/versions")))
        r = t.graph.request("GET", f"drives/{d}/items/{gid}/content")
        detail["content"] = r.status_code
        r = t.graph.http.get(t.graph.url(f"drives/{d}/items/{gid}/content?format=pdf"),
                             headers={"Authorization": f"Bearer {t.reader.app_token()}"}, follow_redirects=False)
        detail["format_pdf"] = r.status_code
        detail["format_pdf_redirect_host"] = httpx.URL(r.headers.get("location", "")).host if r.status_code in (301, 302) else None
        li = t.graph.get(f"drives/{d}/items/{gid}/listItem", params={"$expand": f"fields($select={t.ai_field})"})
        detail["ai_use_field"] = (li.get("fields") or {}).get(t.ai_field, "<trống → Excluded>")
        ok = detail["content"] == 200 and detail["format_pdf"] in (200, 302)
        record(1, "Sites.Selected: delta, versions, content, format=pdf, AI_Use", "PASS" if ok else "FAIL", **detail)
        return f
    except (GraphError, AuthError) as e:
        record(1, "Sites.Selected: delta, versions, content, format=pdf, AI_Use", "FAIL", error=str(e)[:300], **detail)
        return None


def test2(t: GraphTenant, f) -> None:
    """acl-reader: all permissions of an item; SharePoint REST role assignments / groups."""
    detail = {}
    try:
        key, d, gid, _ = f
        perms = list(t.graph.pages(f"drives/{d}/items/{gid}/permissions"))
        detail["permissions"] = len(perms)
        detail["grants_mapped"] = t._grants(key, perms)
        url = t.sites[key].get("url")
        if url and t.sp_scope:
            tok = t.reader.app_token(t.sp_scope)
            for what in ("roleassignments", "sitegroups"):
                r = t.graph.request("GET", f"{url}/_api/web/{what}", token=tok,
                                    headers={"Accept": "application/json;odata=nometadata"})
                detail[f"rest_{what}"] = r.status_code
            r = t.graph.request("POST", f"{url}/_api/web/getchanges", token=tok,
                                headers={"Accept": "application/json;odata=nometadata"},
                                json={"query": {"Item": True, "RoleAssignmentAdd": True, "RoleAssignmentDelete": True,
                                                "GroupMembershipAdd": True, "GroupMembershipDelete": True}})
            detail["rest_getchanges"] = r.status_code
        ok = detail["permissions"] > 0 and all(v == 200 for k, v in detail.items() if k.startswith("rest_"))
        record(2, "acl-reader: quyền của item + SharePoint REST", "PASS" if ok else "FAIL", **detail)
    except (GraphError, AuthError) as e:
        record(2, "acl-reader: quyền của item + SharePoint REST", "FAIL", error=str(e)[:300], **detail)


def user_token(cfg: dict) -> str | None:
    """Device-code sign-in in the person's own browser; returns a token for the AI API."""
    cid = cfg.get("probe_public_client_id")
    if not cid:
        print("  (thiếu probe_public_client_id trong cấu hình: bỏ qua phép thử 3)")
        return None
    base = f"https://login.microsoftonline.com/{cfg['tenant_id']}/oauth2/v2.0"
    scope = cfg.get("api_scope", f"api://{cfg['api']['client_id']}/Chat.Use")
    h = httpx.Client(timeout=30)
    d = h.post(f"{base}/devicecode", data={"client_id": cid, "scope": scope}).json()
    print("\n  " + d.get("message", d.get("error_description", "device code failed")) + "\n", flush=True)
    deadline = time.time() + int(d.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(int(d.get("interval", 5)))
        r = h.post(f"{base}/token", data={"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                          "client_id": cid, "device_code": d["device_code"]}).json()
        if "access_token" in r:
            return r["access_token"]
        if r.get("error") not in ("authorization_pending", "slow_down"):
            print("  sign-in failed:", r.get("error_description", r)[:200])
            return None
    return None


def test3(t: GraphTenant, f, token: str | None, measure: str | None) -> None:
    if not token:
        record(3, "OBO: đọc metadata và nội dung bằng token người dùng", "SKIP", note="chạy với --user")
        return
    oid = jwt_claims(token).get("oid")
    USER_TOKEN.set(token)
    detail = {"oid": oid, "guest": "#EXT#" in jwt_claims(token).get("upn", jwt_claims(token).get("unique_name", ""))}
    try:
        key, d, gid, _ = f
        st, meta = t.get_item_as_user(oid, item_key(d, gid))
        detail["metadata"] = st
        g = t.api.obo_token(token)
        detail["content"] = t.graph.request("GET", f"drives/{d}/items/{gid}/content", token=g).status_code
        status = "PASS" if st in (200, 403, 404) and detail["content"] in (200, 403, 404) else "FAIL"
        if measure:
            print(f"\n  Đo X: hãy GỠ quyền của tài khoản này trên item {measure} trong SharePoint, rồi nhấn Enter…")
            input()
            t0 = time.time()
            while time.time() - t0 < 3600:
                if t.get_item_as_user(oid, measure)[0] != 200:
                    break
                time.sleep(5)
            detail["X_seconds"] = round(time.time() - t0)
        record(3, "OBO: đọc metadata và nội dung bằng token người dùng", status, **detail)
    except Exception as e:     # noqa: BLE001 — every failure here decides "fallback mode"
        record(3, "OBO: đọc metadata và nội dung bằng token người dùng", "FAIL",
               error=str(e)[:300], note="thất bại → chế độ dự phòng (kế hoạch §3.6)", **detail)


def test5(t: GraphTenant, label_item: str | None) -> None:
    if not label_item:
        record(5, "File nhãn mã hóa: kiểm byte sau khi tải", "MANUAL", note="truyền --label-item <item_id> của một file có nhãn mã hóa")
        return
    data = t.download(label_item)
    res = safety.inspect(data, Path(t.items.get(label_item, {}).get("name", "x.docx")).suffix.lstrip("."))
    # PASS = the bytes we get are still encrypted, so the safety check keeps the file out of AI
    record(5, "File nhãn mã hóa: kiểm byte sau khi tải", "PASS" if res.encrypted else "FAIL",
           bytes=len(data), safety=res.reason)


def test8(t: GraphTenant, f, n: int = 60) -> None:
    key, d, gid, _ = f
    t.graph.throttled = 0
    t0, codes, headers = time.time(), {}, {}
    for _ in range(n):
        r = t.graph.request("GET", f"drives/{d}/items/{gid}", params={"$select": "id,cTag"})
        codes[r.status_code] = codes.get(r.status_code, 0) + 1
        for h in ("RateLimit-Limit", "RateLimit-Remaining", "RateLimit-Reset"):
            if h in r.headers:
                headers[h] = r.headers[h]
    record(8, f"Throttling: {n} lượt đọc liên tiếp (app-only)", "PASS" if not t.graph.throttled else "WARN",
           seconds=round(time.time() - t0, 1), http_status=codes, retried_429=t.graph.throttled, headers=headers)


def manual() -> None:
    record(4, "SSE qua reverse proxy DMZ, câu trả lời > 3 phút", "MANUAL",
           how="curl -N https://ai.<miền>/api/chat … qua proxy; xác nhận không bị cắt và có heartbeat")
    record(6, "Khách trên thiết bị không quản lý mở PDF scan ở chế độ giới hạn", "MANUAL",
           how="đăng nhập khách trên máy cá nhân, mở link trích dẫn của PDF scan")
    record(7, "Lần đọc app-only hiện trong nhật ký Purview, lọc được theo app ID", "MANUAL",
           how="Purview Audit: Activities = FileAccessed, lọc AppId = reader client_id, trong khung giờ chạy probe")
    record(9, "gVisor (runsc) với PaddleOCR-VL và bge-m3 trên đúng GPU sẽ mua", "MANUAL",
           how="docker run --runtime=runsc --gpus all … trên máy chủ GPU")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(settings.m365_config))
    ap.add_argument("--example-config", action="store_true")
    ap.add_argument("--user", action="store_true", help="test 3: a test user signs in (device code)")
    ap.add_argument("--measure-x", metavar="ITEM_ID", help="test 3: measure revocation latency on this item")
    ap.add_argument("--label-item", metavar="ITEM_ID", help="test 5: item with an encrypting sensitivity label")
    a = ap.parse_args(argv)
    if a.example_config:
        print(json.dumps(EXAMPLE, ensure_ascii=False, indent=1))
        return 0
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    t = GraphTenant(cfg)
    print(f"Tenant {cfg['tenant_id']} · {len(cfg['sites'])} site\n")
    f = test1(t)
    if f:
        test2(t, f)
    test3(t, f, user_token(cfg) if a.user and f else None, a.measure_x)
    test5(t, a.label_item)
    if f:
        test8(t, f)
    manual()
    out = ROOT / "logs" / f"m365_probe-{datetime.now():%Y%m%d-%H%M}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(R, ensure_ascii=False, indent=1))
    fails = [k for k, v in R.items() if v["status"] == "FAIL"]
    print(f"\nKết quả: {out}  ·  {len(fails)} phép thử thất bại {fails if fails else ''}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
