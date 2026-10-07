"""Put the hard-scan set (data/eval/hard_scans) into the demo data room so the presenter can
ask about rotated, photographed, faxed and stamped documents and see the OCR safeguards
(clean-up steps, second-reader number check, crop of the original region).

Files go to COMMON/Ho-so-scan-thuc-te (inherits COMMON permissions). Idempotent.
Usage: .venv/bin/python scripts/add_hard_scans.py   (then restart the app: it ingests them)
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "eval" / "hard_scans"
TEN = ROOT / "data" / "tenant"
FOLDER = "Ho-so-scan-thuc-te"


def main() -> int:
    truth = json.loads((SRC / "truth.json").read_text(encoding="utf-8"))["docs"]
    t = json.loads((TEN / "tenant.json").read_text(encoding="utf-8"))
    have = {i["id"] for i in t["items"]}
    if not any(f["site"] == "COMMON" and f["path"] == FOLDER for f in t["folders"]):
        t["folders"].append({"site": "COMMON", "path": FOLDER, "unique": False, "grants": []})
    dest = TEN / "files" / "COMMON" / FOLDER
    dest.mkdir(parents=True, exist_ok=True)
    added = 0
    for d in truth:
        iid = "scan-" + d["file"].split("-")[1]
        if iid in have:
            continue
        name = d["file"]
        shutil.copy2(SRC / name, dest / name)
        t["items"].append({"id": iid, "site": "COMMON", "path": FOLDER, "name": name, "ext": d["format"],
                           "file": f"COMMON/{FOLDER}/{name}", "ai_use": "Allowed", "label": "Hạn chế - Data Room",
                           "encrypted": False, "malware": False, "unique": False, "grants": [],
                           "pending_versions": [], "title": d["title"], "version": 1,
                           "ctag": f"c-{iid}-1", "etag": f"e-{iid}-1"})
        added += 1
    (TEN / "tenant.json").write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
    orig = TEN / "tenant.original.json"
    if orig.exists():  # keep "Khôi phục bản gốc" consistent with the new files
        o = json.loads(orig.read_text(encoding="utf-8"))
        o["items"] = [i for i in o["items"] if not i["id"].startswith("scan-")] + \
                     [i for i in t["items"] if i["id"].startswith("scan-")]
        o["folders"] = t["folders"]
        orig.write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Đã thêm {added} hồ sơ scan vào COMMON/{FOLDER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
