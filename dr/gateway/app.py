"""FastAPI gateway: demo sign-in, chat, scope, permission matrix, scenarios, audit,
and a "SharePoint viewer" endpoint that serves originals only if SharePoint allows it."""
from __future__ import annotations

import io
import logging
import mimetypes
import queue
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dr import audit
from dr.config import RATE_MESSAGE, settings
from dr.connector.sync import Connector
from dr.core import answer as answer_mod
from dr.core.index import SearchIndex
from dr.core.pgindex import make_index
from dr.db import pg
from dr.gateway import accounts, auth, scenarios
from dr.gateway import admin as admin_mod
from dr.ingest import ocr, pipeline
from dr.security import ratelimit
from dr.tenant.service import FakeTenant

log = logging.getLogger("gateway")
WEB = settings.root / "web"


class State:
    tenant: FakeTenant
    connector: Connector
    index: object
    deps: answer_mod.Deps | None = None
    stop = threading.Event()
    ingest_q: "queue.Queue[str]" = queue.Queue()
    ingest_busy = False
    last_ingest: list[dict] = []
    models_ready = False


S = State()


def _ingest_worker():
    while not S.stop.is_set():
        try:
            S.ingest_q.get(timeout=1)
        except queue.Empty:
            continue
        while not S.ingest_q.empty():  # coalesce bursts
            S.ingest_q.get_nowait()
        S.ingest_busy = True
        try:
            res = pipeline.ingest_pending(S.tenant, workers=2)
            S.last_ingest = (res + S.last_ingest)[:50]
            if res:
                S.index.refresh()
        except Exception:
            log.exception("background ingest failed")
        finally:
            S.ingest_busy = False


def _on_changes(ch: dict):
    if ch["items_changed"] or ch["ctag_changed"] or ch["items_deleted"]:
        if not getattr(S.index, "in_db", False):
            S.index.refresh()      # in-memory index: drop non-current / deleted chunks right away
                                   # (in Postgres, RLS already hides them inside the search query)
        S.ingest_q.put("go")


def _warm_models():
    try:
        S.deps = answer_mod.Deps.real()
        S.deps.rerank("khởi động", ["khởi động"])
        S.deps.nli("khởi động", "khởi động")
        S.deps.embed_query("khởi động")
        S.models_ready = True
    except Exception:
        log.exception("model warm-up failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    pg.ensure_cluster()
    S.tenant = FakeTenant()
    S.connector = Connector(S.tenant)
    S.connector.full_resync()
    S.index = make_index()
    S.index.refresh()
    S.stop.clear()
    threading.Thread(target=S.connector.run_forever, args=(S.stop, _on_changes), daemon=True).start()
    threading.Thread(target=_ingest_worker, daemon=True).start()
    threading.Thread(target=_warm_models, daemon=True).start()
    S.ingest_q.put("go")
    yield
    S.stop.set()


app = FastAPI(title="Data Room AI – demo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")


# ------------------------------------------------------------------ auth helpers
def current(authorization: str | None = Header(default=None)) -> dict:
    claims = auth.verify((authorization or "").removeprefix("Bearer ").strip())
    if not claims:
        raise HTTPException(401, "Phiên đăng nhập không hợp lệ hoặc đã hết hạn")
    return claims


def admin_only(claims: dict = Depends(current)) -> dict:
    if claims["oid"] != auth.ADMIN_OID:
        raise HTTPException(403, "Chỉ quản trị viên demo")
    return claims


def _groups_of(oid: str) -> list[str]:
    return sorted(g for g, v in S.tenant.groups.items() if oid in v["members"])


app.include_router(admin_mod.build_router(S, admin_only, lambda ch: _on_changes(ch)))


# ------------------------------------------------------------------ pages
@app.get("/", response_class=HTMLResponse)
def home():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for f in ("style.css", "app.js"):  # cache-bust static assets on every change
        html = html.replace(f"/static/{f}", f"/static/{f}?v={int((WEB / f).stat().st_mtime)}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/api/auth/demo-accounts")
def demo_accounts():
    """E-mails of the demo accounts for the sign-in helper (no secrets)."""
    out = [{"email": a["email"], "name": a["name"], "org": a.get("org", ""), "type": "admin", "groups": []}
           for a in S.tenant.admins.values()]
    out += [{"email": u.get("email", ""), "name": u["name"], "org": u.get("org", ""), "type": u.get("type", "guest"),
             "groups": _groups_of(u["oid"]), "enabled": u.get("enabled", True)} for u in S.tenant.users.values()]
    return out


class LoginIn(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginIn):
    email = body.email.strip().lower()
    wait = accounts.locked(email)
    if wait:
        raise HTTPException(429, f"Đăng nhập sai quá nhiều lần. Thử lại sau {int(wait) + 1} giây.")
    found = accounts.find_account(S.tenant, email)
    if not found or not accounts.check_password(body.password, found[1].get("pw")):
        accounts.record_failure(email)
        raise HTTPException(401, "Email hoặc mật khẩu không đúng")
    kind, rec = found
    if kind == "user" and not rec.get("enabled", True):
        raise HTTPException(403, "Tài khoản đã bị vô hiệu hóa trong Entra ID")
    accounts.clear_failures(email)
    roles = ["Admin"] if kind == "admin" else rec.get("roles", [])
    oid = auth.ADMIN_OID if kind == "admin" else rec["oid"]
    audit.append(oid, "sign_in", {"email": email})
    return {"token": auth.issue(oid, roles, rec["name"]), "oid": oid}


@app.get("/api/me")
def me(claims: dict = Depends(current)):
    oid = claims["oid"]
    if oid == auth.ADMIN_OID:
        a = next(iter(S.tenant.admins.values()), {"name": "Quản trị", "email": "", "org": ""})
        return {"oid": oid, "name": a["name"], "email": a.get("email", ""), "org": a.get("org", ""),
                "type": "admin", "roles": ["Admin"], "groups": [], "exp": claims["exp"]}
    u = S.tenant.users.get(oid, {})
    return {"oid": oid, "name": u.get("name", claims["name"]), "email": u.get("email", ""), "org": u.get("org", ""),
            "type": u.get("type", "guest"), "roles": claims["roles"], "groups": _groups_of(oid),
            "sites": [{"id": s["id"], "name": s["name"]} for s in S.tenant.sites.values()
                      if set(s.get("groups", [])) & set(_groups_of(oid))],
            "exp": claims["exp"]}


class ChatIn(BaseModel):
    question: str
    scope_site: str | None = None


@app.post("/api/chat")
async def chat(body: ChatIn, claims: dict = Depends(current)):
    if claims["oid"] == auth.ADMIN_OID:
        raise HTTPException(400, "Hãy chọn một danh tính người dùng để hỏi")
    if S.deps is None:
        raise HTTPException(503, "Model đang khởi động, thử lại sau ít giây")
    wait = ratelimit.limiter.check(claims["oid"])
    if wait:
        audit.append(claims["oid"], "rate_limited", {"retry_after": round(wait)})
        raise HTTPException(429, RATE_MESSAGE.format(seconds=int(wait) + 1), headers={"Retry-After": str(int(wait) + 1)})

    def run():
        with ratelimit.limiter.slots:     # bounded concurrent LLM work across all users
            return answer_mod.ask(S.tenant, S.index, claims["oid"], claims["roles"], body.question, S.deps,
                                  body.scope_site)
    return await run_in_threadpool(run)


# ------------------------------------------------------------------ scope / matrix
def _item_rows() -> dict[str, dict]:
    with pg.admin() as c:
        rows = c.execute("SELECT item_id, status, reason, ai_use, encrypted, malware, chunk_count FROM items").fetchall()
    return {r[0]: {"status": r[1], "reason": r[2], "ai_use": r[3], "encrypted": r[4], "malware": r[5],
                   "chunks": r[6]} for r in rows}


def _ai_items(oid: str) -> dict[str, int]:
    with pg.as_principal(oid) as cur:
        return {r[0]: r[1] for r in cur.execute("SELECT item_id, count(*) FROM chunks GROUP BY item_id")}


def _ai_status(it: dict, db: dict | None, ai_items: dict) -> tuple[str, str]:
    if db is None:
        return "pending", "Chưa đồng bộ"
    if it["id"] in ai_items:
        return "ai_ok", f"{ai_items[it['id']]} đoạn"
    if db["malware"]:
        return "malware", db["reason"] or "Có mã độc"
    if db["encrypted"]:
        return "encrypted", db["reason"] or "Mã hóa"
    if db["ai_use"] not in ("Allowed", "OnPremOnly"):
        return "excluded", f"AI_Use = {db['ai_use']}"
    if db["status"] in ("pending",):
        return "pending", "Đang nạp"
    if db["status"] in ("skipped", "error"):
        return "unsupported", db["reason"] or db["status"]
    return "ai_blocked", "AI đang chặn (thu hồi/chờ SharePoint)"


@app.get("/api/scope")
def scope(claims: dict = Depends(current)):
    if claims["oid"] == auth.ADMIN_OID:
        raise HTTPException(400, "Hãy chọn một danh tính người dùng")
    return _scope(claims["oid"])


@app.get("/api/scope_of/{oid}")
def scope_of(oid: str, _: dict = Depends(admin_only)):
    if oid not in S.tenant.users:
        raise HTTPException(404, "Không có người dùng này")
    return _scope(oid)


def _scope(oid: str) -> dict:
    db = _item_rows()
    ai_items = _ai_items(oid)
    sites: dict[str, dict] = {}
    counts: dict[str, int] = {}
    ai_only = []
    for iid, it in S.tenant.items.items():
        sp = S.tenant.sp_can_read(oid, iid)
        if not sp:
            if iid in ai_items:
                ai_only.append(iid)  # should never happen — surfaced loudly
            continue
        st, why = _ai_status(it, db.get(iid), ai_items)
        counts[st] = counts.get(st, 0) + 1
        site = sites.setdefault(it["site"], {"site": it["site"], "name": S.tenant.sites[it["site"]]["name"],
                                             "folders": {}})
        site["folders"].setdefault(it["path"], []).append(
            {"item_id": iid, "name": it["name"], "ext": it["ext"], "status": st, "detail": why})
    out_sites = []
    for s in sorted(sites.values(), key=lambda x: x["site"]):
        out_sites.append({"site": s["site"], "name": s["name"],
                          "folders": [{"path": p, "files": sorted(f, key=lambda x: x["name"])}
                                      for p, f in sorted(s["folders"].items())]})
    return {"oid": oid, "sites": out_sites, "counts": counts, "sharepoint_total": sum(counts.values()),
            "ai_total": counts.get("ai_ok", 0), "violations_ai_without_sharepoint": ai_only,
            "groups": _groups_of(oid), "roles": S.tenant.users[oid].get("roles", [])}


@app.get("/api/matrix")
def matrix(_: dict = Depends(admin_only)):
    db = _item_rows()
    out = []
    for oid, u in S.tenant.users.items():
        ai_items = _ai_items(oid)
        row = {"oid": oid, "name": u["name"], "org": u.get("org", ""), "groups": _groups_of(oid),
               "enabled": u.get("enabled", True), "roles": u.get("roles", []), "sites": {}}
        for sid in S.tenant.sites:
            row["sites"][sid] = {"sharepoint": 0, "ai": 0, "lag": 0}
        for iid, it in S.tenant.items.items():
            cell = row["sites"][it["site"]]
            sp = S.tenant.sp_can_read(oid, iid)
            cell["sharepoint"] += sp
            cell["ai"] += iid in ai_items
            if sp and iid not in ai_items and db.get(iid, {}).get("status") == "indexed":
                cell["lag"] += 1
        out.append(row)
    return {"sites": [{"id": s, "name": v["name"]} for s, v in S.tenant.sites.items()], "rows": out}


# ------------------------------------------------------------------ status / scenarios / audit
@app.get("/api/status")
def status(_: dict = Depends(current)):
    with pg.admin() as c:
        feeds = {r[0]: round(r[1], 1) for r in c.execute(
            "SELECT feed, EXTRACT(EPOCH FROM clock_timestamp() - last_ok) FROM feed_status")}
        items = {r[0]: r[1] for r in c.execute("SELECT status, count(*) FROM items GROUP BY status")}
        revs = [{"oid": r[0], "group": r[1], "until": r[2].isoformat()} for r in
                c.execute("SELECT oid, group_id, until FROM revocations ORDER BY created_at")]
        deny = [{"oid": r[0], "reason": r[1]} for r in c.execute("SELECT oid, reason FROM deny_list")]
    return {"feeds": feeds, "feed_max_age": settings.feed_max_age_seconds, "items": items,
            "index": S.index.stats(), "revocations": revs, "deny_list": deny,
            "sharepoint_pending": S.tenant.membership_lag_status(), "entra_paused": S.tenant.entra_paused,
            "connector_error": S.connector.last_error, "ingest_busy": S.ingest_busy,
            "models_ready": S.models_ready, "ocr_server": ocr.vl_available(),
            "models": {"llm": settings.llm_model, "embed": settings.embed_model, "rerank": settings.rerank_model,
                       "nli": settings.nli_model, "ocr": "PaddleOCR-VL-1.6 (MLX)"}}


class ScenarioIn(BaseModel):
    params: dict = {}


@app.post("/api/scenario/{name}")
def scenario(name: str, body: ScenarioIn | None = None, _: dict = Depends(admin_only)):
    try:
        res = scenarios.run(name, (body.params if body else {}) or {}, S.tenant, S.connector)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    audit.append(auth.ADMIN_OID, "scenario", {"name": name, "title": res["title"]})
    if name == "reset":
        S.index.refresh()
        S.ingest_q.put("go")
    return res


@app.get("/api/audit")
def audit_recent(limit: int = 50, _: dict = Depends(admin_only)):
    return audit.recent(limit)


@app.get("/api/audit/verify")
def audit_verify(_: dict = Depends(admin_only)):
    return audit.verify()


@app.get("/open/{item_id}")
def open_file(item_id: str, t: str = Query(...)):
    """'SharePoint viewer': SharePoint itself decides at open time."""
    claims = auth.verify(t)
    if not claims:
        raise HTTPException(401, "Phiên không hợp lệ")
    if claims["oid"] == auth.ADMIN_OID or not S.tenant.sp_can_read(claims["oid"], item_id):
        raise HTTPException(403, "SharePoint: bạn không có quyền mở tài liệu này")
    p: Path = S.tenant.file_path(item_id)
    mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    if p.suffix.lower() == ".eml":
        mt = "text/plain; charset=utf-8"
    inline = p.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg", ".html", ".txt", ".md", ".csv", ".eml")
    return FileResponse(p, media_type=mt, filename=S.tenant.items[item_id]["name"],
                        content_disposition_type="inline" if inline else "attachment")


@app.get("/crop/{item_id}")
def crop(item_id: str, t: str = Query(...), page: str = Query(...), box: str | None = None):
    """Region of a cleaned scan page, for checking an OCR'd quote against the original.
    Same rule as /open: SharePoint (sp_can_read) decides, and the page must belong to a
    current chunk of this very item."""
    claims = auth.verify(t)
    if not claims:
        raise HTTPException(401, "Phiên không hợp lệ")
    if claims["oid"] == auth.ADMIN_OID or not S.tenant.sp_can_read(claims["oid"], item_id):
        raise HTTPException(403, "SharePoint: bạn không có quyền mở tài liệu này")
    with pg.admin() as c:
        ok = c.execute("SELECT 1 FROM chunks WHERE item_id=%s AND ocr_page=%s AND is_current LIMIT 1",
                       (item_id, page)).fetchone()
    key, _, n = page.partition("/p")
    got = ocr.cached_page(key, int(n)) if ok and n.isdigit() else None
    if not got:
        raise HTTPException(404, "Không có ảnh trang")
    from PIL import Image
    img = Image.open(got[0])
    if box:
        try:
            x0, y0, x1, y1 = (int(v) for v in box.split(","))
        except ValueError:
            raise HTTPException(400, "box không hợp lệ")
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(img.width, x1), min(img.height, y1)
        if x1 - x0 > 10 and y1 - y0 > 10:
            img = img.crop((x0, y0, x1, y1))
    img.thumbnail((1400, 1400))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=85)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/health")
def health():
    return {"ok": True, "time": time.time()}
