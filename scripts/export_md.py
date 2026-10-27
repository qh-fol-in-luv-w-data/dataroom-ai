"""Write the whole data room as Markdown: one `<folder>/<file name>.md` per indexed file (any format: Word,
Excel, PowerPoint, PDF, scans, images), plus INDEX.md listing every file with its status, so the content can
be read, checked or loaded again without parsing or OCR-ing the originals.

Text comes from the chunks in Postgres (what the chat searches), in reading order, one '## <place>' section per
page / sheet / slide. A file OCR-ed on the GPU server (converter 'PaddleOCR-VL-1.6 (inference_ocr)') keeps the
server's own Markdown, copied from --server-md.

    DR_DATA=data/ctg ... python scripts/export_md.py --out data/ctg/md --server-md /Users/me/out_md
"""
from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dr.db import pg  # noqa: E402
from dr.config import settings  # noqa: E402
from dr.ingest import ocr_md  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--server-md", help="Markdown tree from inference_ocr (copied as-is for the files OCR-ed there)")
    a = ap.parse_args()
    out = Path(a.out)
    if a.server_md:
        settings.ocr_md_dir = a.server_md
    with pg.admin() as c:
        items = c.execute("SELECT item_id, path, name, ext, status, reason, chunk_count FROM items "
                          "ORDER BY path, name").fetchall()
        rows = c.execute("SELECT item_id, locator, text, converter FROM chunks WHERE is_current "
                         "ORDER BY item_id, ordinal").fetchall()
    docs: dict[str, dict] = defaultdict(lambda: {"converter": "", "parts": defaultdict(list)})
    for iid, locator, text, converter in rows:
        d = docs[iid]
        d["converter"] = converter
        d["parts"][locator or "Nội dung"].append(text)

    index = ["# Dữ liệu dạng Markdown", "", "| Thư mục | File | Trạng thái | Đọc bằng | Markdown / lý do |", "|---|---|---|---|---|"]
    stats: Counter = Counter()
    for iid, path, name, ext, status, reason, n in items:
        folder = path.strip("/")
        rel = Path(folder) / (name + ".md")
        d = docs.get(iid)
        if status != "indexed" or not d:
            index.append(f"| {folder} | {name} | {status} | | {(reason or '').replace('|', '/')} |")
            stats[status] += 1
            continue
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        src = ocr_md.find(path, name) if d["converter"] == ocr_md.CONVERTER else None
        if src:
            shutil.copyfile(src, dst)
        else:
            lines = [f"# {name}", "", f"<!-- đọc bằng: {d['converter']} -->", ""]
            for place, texts in d["parts"].items():
                lines += [f"## {place}", ""] + [t.strip() + "\n" for t in texts]
            dst.write_text("\n".join(lines), encoding="utf-8")
        link = str(rel).replace(" ", "%20")
        index.append(f"| {folder} | {name} | indexed | {d['converter']} | [{n} đoạn]({link}) |")
        stats["indexed"] += 1
    (out / "INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"{stats['indexed']} file .md -> {out}  ·  INDEX.md: {len(items)} file  ·  {dict(stats)}")


if __name__ == "__main__":
    main()
