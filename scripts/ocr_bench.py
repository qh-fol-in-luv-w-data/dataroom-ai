"""OCR models compared on the CT Group documents themselves: PaddleOCR-VL-1.6 (in use) against OvisOCR2, TeleOCR
and MinerU2.5-Pro.

Set A — pages with a known answer: pages of PDFs that have a text layer (contracts, brochures, price lists) are
rendered to images and read by each model; the PDF's own text is the truth. Measured on words (a model may read
columns in another order, which is not an error): word recall, recall with accents removed, the share of words
read with a wrong tone mark (found without accents but not with them), numbers of 3+ digits read right.
Set B — posters and photos (no truth): words per 100 that the room's own spelling (ocr_accents) would correct,
i.e. tone marks the model got wrong, as a proxy.

    DR_DATA=data/ctg ... python scripts/ocr_bench.py build            # pick and render the pages, once
    DR_DATA=data/ctg ... python scripts/ocr_bench.py run paddle ovis teleocr mineru
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unidecode import unidecode  # noqa: E402

from dr.config import settings  # noqa: E402

OUT = settings.data_dir / "ocr_bench"
N_PAGES, N_IMAGES = 40, 30


# ------------------------------------------------------------------ test set
def build() -> None:
    import pypdfium2 as pdfium
    from dr.db import pg
    from dr.ingest import ocr_md
    from dr.ingest.parsers import _visible_page_text, text_quality
    from dr.tenant.service import FakeTenant
    t = FakeTenant()
    with pg.admin() as c:
        all_pdfs = [r[0] for r in c.execute("SELECT item_id FROM items WHERE ext = 'pdf'")]
        imgs = c.execute("SELECT item_id FROM items WHERE ext IN ('jpg','jpeg','png') AND chunk_count >= 1").fetchall()
    # PDFs whose text is their own text layer (the exported Markdown says 'pdfium-text'): the typed text is the truth
    pdfs = []
    for iid in all_pdfs:
        md = ocr_md.find(t.items[iid]["path"], t.items[iid]["name"])
        if md and "<!-- đọc bằng: pdfium-text -->" in md.read_text(encoding="utf-8")[:300]:
            pdfs.append(iid)
    rnd = random.Random(7)
    rnd.shuffle(pdfs)
    (OUT / "pages").mkdir(parents=True, exist_ok=True)
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    pages, seen_text = [], set()
    for iid in pdfs:
        if len(pages) >= N_PAGES:
            break
        doc = pdfium.PdfDocument(str(t.file_path(iid)))
        try:
            i = rnd.randrange(len(doc))
            page = doc[i]
            text, _ = _visible_page_text(pdfium, page)
            key = text[:200]
            if not (400 <= len(text) <= 4000) or text_quality(text) < 0.9 or key in seen_text:
                continue
            seen_text.add(key)
            scale = min(200 / 72, 2400 / page.get_width())
            name = f"p{len(pages):02d}"
            page.render(scale=scale).to_pil().convert("RGB").save(OUT / "pages" / f"{name}.png")
            (OUT / "pages" / f"{name}.txt").write_text(text, encoding="utf-8")
            pages.append({"id": name, "item_id": iid, "file": t.items[iid]["name"], "page": i + 1})
        finally:
            doc.close()
    rnd.shuffle(imgs)
    images = []
    for (iid,) in imgs[:N_IMAGES]:
        src = t.file_path(iid)
        name = f"i{len(images):02d}{src.suffix.lower()}"
        (OUT / "images" / name).write_bytes(src.read_bytes())
        images.append({"id": name, "item_id": iid, "file": t.items[iid]["name"]})
    (OUT / "set.json").write_text(json.dumps({"pages": pages, "images": images}, ensure_ascii=False, indent=1))
    print(f"{len(pages)} trang có đáp án, {len(images)} ảnh -> {OUT}")


# ------------------------------------------------------------------ readers
def reader(name: str):
    import torch
    from PIL import Image
    dev = "mps" if torch.backends.mps.is_available() else "cpu"

    if name == "paddle":
        from dr.ingest.ocr import _vl_page
        return lambda path: "\n".join(b.text for b in _vl_page(str(path), 1).blocks)

    if name == "ovis":
        from transformers import AutoModelForMultimodalLM, AutoProcessor
        repo = "ATH-MaaS/OvisOCR2"
        proc = AutoProcessor.from_pretrained(repo)
        model = AutoModelForMultimodalLM.from_pretrained(repo, dtype=torch.bfloat16).to(dev).eval()
        prompt = ("Extract all readable content from the image in natural human reading order, as one Markdown "
                  "document. Tables as HTML, formulas as LaTeX, other text as Markdown. Do not translate or paraphrase.")

        def read(path):
            img = Image.open(path).convert("RGB")
            msgs = [{"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": prompt}]}]
            inputs = proc.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True, return_dict=True,
                                              return_tensors="pt", enable_thinking=False).to(dev)
            out = model.generate(**inputs, max_new_tokens=4096, do_sample=False)
            return proc.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        return read

    if name == "teleocr":
        from transformers import AutoModel, AutoProcessor
        from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS

        def default_rope(config, device=None, seq_len=None):
            """The plain RoPE of transformers 4.x ('default'), which TeleOCR's own code asks for and transformers
            5 no longer registers: inverse frequencies base^(-2i/d), no attention scaling."""
            base = getattr(config, "rope_theta", None) or (getattr(config, "rope_parameters", None) or {}).get(
                "rope_theta", 10000.0)
            head_dim = getattr(config, "head_dim", None) or config.hidden_size // config.num_attention_heads
            dim = int(head_dim * getattr(config, "partial_rotary_factor", 1.0))
            inv = 1.0 / (base ** (torch.arange(0, dim, 2, dtype=torch.int64).to(device=device, dtype=torch.float) / dim))
            return inv, 1.0
        ROPE_INIT_FUNCTIONS.setdefault("default", default_rope)
        repo = "StarDoc-AI/TeleOCR"
        # its code declares tied weights as a list (transformers 4); transformers 5 wants a mapping. The declaration
        # is dropped and the output layer is tied to the input embeddings by hand after loading
        # (config: tie_word_embeddings = true)
        from transformers import AutoConfig
        from transformers.dynamic_module_utils import get_class_from_dynamic_module
        cls = get_class_from_dynamic_module(AutoConfig.from_pretrained(repo, trust_remote_code=True).auto_map["AutoModel"],
                                            repo)
        for c in cls.__mro__:
            if isinstance(c.__dict__.get("_tied_weights_keys"), list):
                c._tied_weights_keys = None
        proc = AutoProcessor.from_pretrained(repo, trust_remote_code=True, use_fast=True)
        model = AutoModel.from_pretrained(repo, trust_remote_code=True, dtype=torch.bfloat16)
        if getattr(model, "lm_head", None) is not None:
            model.lm_head.weight = model.get_input_embeddings().weight
        model = model.to(dev).eval()

        def read(path):
            img = Image.open(path).convert("RGB")
            msgs = [{"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": [{"type": "image"},
                                                 {"type": "text", "text": "Please output the text content from the image."}]}]
            text = proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
            inputs = proc(text=[text], images=[img], padding=True, return_tensors="pt").to(dev)
            inputs.pop("mm_token_type_ids", None)        # added by the transformers 5 processor, unknown to its code
            out = model.generate(**inputs, use_cache=True, max_new_tokens=4096, do_sample=False)
            return proc.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True,
                                     clean_up_tokenization_spaces=False)[0].strip()
        return read

    if name == "mineru":
        from mineru_vl_utils import MinerUClient
        from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
        repo = "opendatalab/MinerU2.5-Pro-2604-1.2B"
        model = Qwen2VLForConditionalGeneration.from_pretrained(repo, dtype=torch.bfloat16).to(dev).eval()
        proc = AutoProcessor.from_pretrained(repo, use_fast=True)
        client = MinerUClient(backend="transformers", model=model, processor=proc)

        def read(path):
            blocks = client.two_step_extract(Image.open(path).convert("RGB"))
            return "\n".join(str(b.get("content") or "") for b in blocks if isinstance(b, dict))
        return read
    raise SystemExit(f"không biết model {name}")


# ------------------------------------------------------------------ metrics
_TAG = re.compile(r"<[^>]+>|\$+|\\[a-z]+|[*#|`]")
_W = re.compile(r"[^\W_]+", re.UNICODE)
_N = re.compile(r"\d[\d.,]*\d")


def words(text: str) -> list[str]:
    from dr.ingest.ocr import clean_math
    return [w.lower() for w in _W.findall(_TAG.sub(" ", clean_math(text)))]


def page_scores(truth: str, read: str) -> dict:
    t, r = Counter(words(truth)), Counter(words(read))
    tf, rf = Counter(), Counter()
    for w, n in t.items():
        tf[unidecode(w)] += n
    for w, n in r.items():
        rf[unidecode(w)] += n
    total = sum(t.values()) or 1
    exact = sum((t & r).values())
    folded = sum((tf & rf).values())
    nums_t = {re.sub(r"\D", "", n) for n in _N.findall(truth) if len(re.sub(r"\D", "", n)) >= 3}
    nums_r = {re.sub(r"\D", "", n) for n in _N.findall(read)}
    return {"recall": exact / total, "recall_noaccent": folded / total, "tone_errors": max(0, folded - exact) / total,
            "numbers": (len(nums_t & nums_r) / len(nums_t)) if nums_t else None, "extra": max(0, sum(r.values()) - total)}


def run(models: list[str], n_pages: int | None = None, n_images: int | None = None, reuse: set = frozenset()) -> None:
    """Each model on the first n_pages pages and n_images images of the set; a model in `reuse` is scored from
    the reads saved by an earlier run (results/<model>_<id>.txt) instead of reading again."""
    from dr.ingest import ocr_accents
    spec = json.loads((OUT / "set.json").read_text())
    pages, images = spec["pages"][:n_pages], spec["images"][:n_images]
    res_dir = OUT / "results"
    res_dir.mkdir(exist_ok=True)
    old = json.loads((OUT / "summary.json").read_text()) if (OUT / "summary.json").exists() else {}
    summary = {}
    for m in models:
        saved = m in reuse

        def from_saved(path: Path, m=m) -> str:
            sid = path.stem if path.parent.name == "pages" else path.name      # p00 / i00.jpg, as when saved
            return (res_dir / f"{m}_{sid}.txt").read_text(encoding="utf-8")
        try:
            read = from_saved if saved else reader(m)
        except Exception as e:                          # a model that does not load is reported, the others still run
            print(f"{m}: KHÔNG NẠP ĐƯỢC MODEL – {e.__class__.__name__}: {str(e)[:200]}", flush=True)
            continue
        rows, secs = [], []
        for p in pages:
            t0 = time.time()
            try:
                text = read(OUT / "pages" / f"{p['id']}.png")
            except Exception as e:                      # a failure counts as an empty read, and is shown
                text = ""
                print(f"  {m} {p['id']}: lỗi {e.__class__.__name__}: {str(e)[:120]}", flush=True)
            secs.append(time.time() - t0)
            if not saved:
                (res_dir / f"{m}_{p['id']}.txt").write_text(text, encoding="utf-8")
            rows.append(page_scores((OUT / "pages" / f"{p['id']}.txt").read_text(encoding="utf-8"), text))
            print(f"  {m} {p['id']} {secs[-1]:5.1f}s recall {rows[-1]['recall']:.2f}", flush=True)
        fixes = total = 0
        for im in images:
            t0 = time.time()
            try:
                text = read(OUT / "images" / im["id"])
            except Exception as e:
                text = ""
                print(f"  {m} {im['id']}: lỗi {e.__class__.__name__}: {str(e)[:120]}", flush=True)
            secs.append(time.time() - t0)
            if not saved:
                (res_dir / f"{m}_{im['id']}.txt").write_text(text, encoding="utf-8")
            ws = words(text)
            fixed = words(ocr_accents.fix(" ".join(ws)))
            fixes += sum(a != b for a, b in zip(ws, fixed))
            total += len(ws)
        avg = lambda k: sum(r[k] for r in rows if r[k] is not None) / max(1, sum(r[k] is not None for r in rows))  # noqa: E731
        summary[m] = {"recall": avg("recall"), "recall_noaccent": avg("recall_noaccent"), "tone_errors": avg("tone_errors"),
                      "numbers": avg("numbers"), "poster_tone_fix_per100": 100 * fixes / max(1, total),
                      "poster_words": total,
                      # a reused model's speed is the one measured when it read the pages
                      "sec_per_page": old.get(m, {}).get("sec_per_page", 0.0) if saved else sum(secs) / len(secs)}
        print(m, json.dumps(summary[m], ensure_ascii=False), flush=True)
        del read
        import gc
        gc.collect()
    tag = f"{len(pages)}p{len(images)}i"
    if not n_pages and not n_images:
        old.update({m: s for m, s in summary.items() if m not in reuse})
        (OUT / "summary.json").write_text(json.dumps(old, ensure_ascii=False, indent=1))
    (OUT / f"summary_{tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"\n{len(pages)} trang có đáp án, {len(images)} ảnh")
    print("Model      Từ đúng  Bỏ dấu  Sai dấu  Số đúng  Poster sai dấu/100  Giây/trang")
    for m, s in summary.items():
        print(f"{m:10} {s['recall']:7.1%} {s['recall_noaccent']:7.1%} {s['tone_errors']:7.1%} {s['numbers']:7.1%} "
              f"{s['poster_tone_fix_per100']:18.1f} {s['sec_per_page']:10.1f}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run"])
    ap.add_argument("models", nargs="*", default=["paddle"])
    ap.add_argument("--pages", type=int, help="only the first N pages of the set")
    ap.add_argument("--images", type=int, help="only the first N images of the set")
    ap.add_argument("--reuse", nargs="*", default=[], help="models scored from their saved reads, not read again")
    a = ap.parse_args()
    build() if a.cmd == "build" else run(a.models, a.pages, a.images, set(a.reuse))
