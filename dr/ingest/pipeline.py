"""Ingestion: tenant file -> safety -> parse/OCR -> chunks -> embeddings -> Postgres.

Re-checks the item's ctag and AI flag inside the write transaction, so a file that
changed or was excluded while it was being parsed is never written as current.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from dr.db import pg
from dr.ingest import safety
from dr.core.pgindex import tsv_literal, vec_literal
from dr.ingest.chunker import Chunk, chunk, fold
from dr.ingest.parsers import SUPPORTED, Block, ParsedDoc, parse
from dr.models.embed import embed_texts
from dr.tenant.service import FakeTenant

log = logging.getLogger("ingest")
AI_VALUES = ("Allowed", "OnPremOnly")


def _mark(item_id: str, status: str, reason: str | None = None, **extra) -> None:
    sets = ", ".join(f"{k}=%s" for k in extra)
    with pg.admin() as c:
        c.execute(f"UPDATE items SET status=%s, reason=%s{', ' + sets if sets else ''}, updated_at=now() "
                  "WHERE item_id=%s", (status, reason, *extra.values(), item_id))
        c.commit()


def _parse_with_attachments(data: bytes, ext: str, name: str, depth: int = 0) -> ParsedDoc:
    doc = parse(data, ext, name)
    blocks = list(doc.blocks)
    notes = list(doc.notes)
    converters = {doc.converter}
    for att_name, att_ext, att_data in doc.attachments:
        if depth > 1 or att_ext not in SUPPORTED:
            notes.append(f"Bỏ qua đính kèm {att_name} (định dạng .{att_ext})")
            continue
        s = safety.inspect(att_data, att_ext)
        if not s.ok:
            notes.append(f"Bỏ qua đính kèm {att_name}: {s.reason}")
            continue
        try:
            sub = _parse_with_attachments(att_data, att_ext, att_name, depth + 1)
        except Exception as e:
            notes.append(f"Không đọc được đính kèm {att_name}: {e}")
            continue
        prefix = f"Đính kèm: {att_name}" if ext == "eml" else att_name
        for b in sub.blocks:
            blocks.append(Block(b.text, f"{prefix} › {b.locator}", b.kind, b.ocr, b.meta))
        notes.extend(sub.notes)
        converters.add(sub.converter)
    return ParsedDoc(blocks, "+".join(sorted(converters)), notes=notes)


def ingest_item(tenant: FakeTenant, item_id: str) -> dict:
    t0 = time.time()
    with pg.admin() as c:
        row = c.execute("SELECT name, ext, ctag, ai_use, encrypted, malware FROM items WHERE item_id=%s",
                        (item_id,)).fetchone()
    if not row:
        return {"item_id": item_id, "status": "missing"}
    name, ext, ctag, ai_use, encrypted, malware = row
    if malware:
        _mark(item_id, "skipped", "SharePoint/Defender đánh dấu có mã độc")
        return {"item_id": item_id, "status": "skipped"}
    if encrypted:
        _mark(item_id, "skipped", "Nhãn nhạy cảm có mã hóa")
        return {"item_id": item_id, "status": "skipped"}
    if ai_use not in AI_VALUES:
        _mark(item_id, "skipped", f"AI_Use = {ai_use}")
        return {"item_id": item_id, "status": "skipped"}
    if ext not in SUPPORTED:
        _mark(item_id, "skipped", f"Định dạng .{ext} chưa hỗ trợ (chỉ lưu metadata)")
        return {"item_id": item_id, "status": "skipped"}

    data = tenant.download(item_id)
    s = safety.inspect(data, ext)
    if not s.ok:
        _mark(item_id, "skipped", s.reason, encrypted=s.encrypted or encrypted, malware=s.malware or malware)
        return {"item_id": item_id, "status": "skipped", "reason": s.reason}
    try:
        doc = _parse_with_attachments(data, ext, name)
    except Exception as e:
        log.exception("parse failed for %s", item_id)
        _mark(item_id, "error", f"Lỗi đọc file: {e.__class__.__name__}: {e}"[:300])
        return {"item_id": item_id, "status": "error"}
    chunks: list[Chunk] = chunk(doc.blocks)
    if not chunks:
        _mark(item_id, "skipped", "Không trích được nội dung")
        return {"item_id": item_id, "status": "skipped"}
    vecs = embed_texts([f"{name}\n{ch.text}" for ch in chunks])

    with pg.admin() as c:
        cur = c.execute("SELECT ctag, ai_use, encrypted, malware FROM items WHERE item_id=%s FOR UPDATE",
                        (item_id,)).fetchone()
        if not cur or cur[0] != ctag or cur[1] not in AI_VALUES or cur[2] or cur[3]:
            c.rollback()
            return {"item_id": item_id, "status": "stale"}
        site = c.execute("SELECT site_id FROM items WHERE item_id=%s", (item_id,)).fetchone()[0]
        c.execute("DELETE FROM chunks WHERE item_id=%s", (item_id,))
        with c.cursor() as cc:
            cc.executemany(
                "INSERT INTO chunks(item_id, site_id, ctag, is_current, ordinal, locator, kind, text, text_folded, "
                "injection_flag, ocr, converter, embedding, emb, tsv, tlen, ocr_doubt, ocr_page) "
                "VALUES (%s,%s,%s,true,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::halfvec,%s::tsvector,%s,%s,%s)",
                [(item_id, site, ctag, ch.ordinal, ch.locator, ch.kind, ch.text, fold(ch.text), ch.injection_flag,
                  ch.ocr, doc.converter, vecs[i].tolist(), vec_literal(vecs[i]), *tsv_literal(ch.text),
                  ch.doubt or None, ch.page_key) for i, ch in enumerate(chunks)])
        reason = "; ".join(doc.notes)[:500] or None
        c.execute("UPDATE items SET status='indexed', reason=%s, ingested_ctag=%s, chunk_count=%s, updated_at=now() "
                  "WHERE item_id=%s", (reason, ctag, len(chunks), item_id))
        c.commit()
    return {"item_id": item_id, "status": "indexed", "chunks": len(chunks), "converter": doc.converter,
            "seconds": round(time.time() - t0, 1)}


def pending_items() -> list[str]:
    with pg.admin() as c:
        return [r[0] for r in c.execute(
            "SELECT item_id FROM items WHERE status='pending' OR (status='indexed' AND ingested_ctag IS DISTINCT FROM ctag) "
            "ORDER BY (ext IN ('pdf','png','jpg')), size")]


def ingest_pending(tenant: FakeTenant, workers: int = 3, progress=None) -> list[dict]:
    ids = pending_items()
    results = []
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(lambda i: _safe(tenant, i), ids):
            results.append(r)
            if progress:
                progress(len(results), len(ids), r)
    return results


def _safe(tenant, item_id):
    try:
        return ingest_item(tenant, item_id)
    except Exception as e:
        log.exception("ingest failed %s", item_id)
        _mark(item_id, "error", f"{e.__class__.__name__}: {e}"[:300])
        return {"item_id": item_id, "status": "error", "error": str(e)}
