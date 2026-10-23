"""Vintern-1B-v3.5 (5CD-AI, InternVL2.5 + Qwen2, Vietnamese) as a page reader.

Runs in-process with transformers on the Apple GPU (MPS) in float16. The page is cut into 448 px
tiles (InternVL "dynamic preprocess", up to MAX_TILES plus a thumbnail). The prompt asks for a
verbatim copy: the model's usual "extract the main information as markdown" prompt paraphrased and
added comments of its own on real pages; "chép lại nguyên văn" kept to the page. Greedy decoding with a repetition penalty:
small VLMs otherwise loop on long digit runs ("1000000000…").
"""
from __future__ import annotations

import os
import re
import threading

os.environ.setdefault("HF_HUB_OFFLINE", "1")   # the model ships its own code: use the copy on disk, never a newer one

from PIL import Image

MODEL_ID = os.environ.get("DR_VINTERN_MODEL", "5CD-AI/Vintern-1B-v3_5")
MAX_TILES = int(os.environ.get("DR_VINTERN_TILES", "6"))
# few text boxes (a banner, a slide photo): fewer tiles read the same text faster
SMALL_TILES = int(os.environ.get("DR_VINTERN_TILES_SPARSE", "4"))
MAX_NEW_TOKENS = int(os.environ.get("DR_VINTERN_MAX_TOKENS", "1536"))
PROMPT = "Chép lại nguyên văn toàn bộ chữ trong ảnh, từng dòng, không giải thích."
SIZE = 448
_MEAN, _STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)

_lock = threading.Lock()
_model = _tok = _device = None


def _load():
    global _model, _tok, _device
    if _model is None:
        import torch
        from transformers import AutoModel, AutoTokenizer
        _device = "mps" if torch.backends.mps.is_available() else "cpu"
        dtype = torch.float16 if _device == "mps" else torch.float32
        from transformers.dynamic_module_utils import get_class_from_dynamic_module
        # transformers 5 expects all_tied_weights_keys (set by post_init, which the model's own code does not
        # call); nothing needs tying: the checkpoint has its own language_model.lm_head.weight
        cls = get_class_from_dynamic_module("modeling_internvl_chat.InternVLChatModel", MODEL_ID)
        if not hasattr(cls, "all_tied_weights_keys"):
            cls.all_tied_weights_keys = {}
        _model = AutoModel.from_pretrained(MODEL_ID, dtype=dtype, trust_remote_code=True, local_files_only=True,
                                           low_cpu_mem_usage=True, use_flash_attn=False).eval().to(_device)
        _tok = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True, use_fast=False, local_files_only=True)
    return _model, _tok


def _tiles(img: Image.Image, max_tiles: int = MAX_TILES) -> list[Image.Image]:
    """InternVL dynamic tiling: the grid (cols x rows <= max_tiles) closest to the page's aspect ratio."""
    w, h = img.size
    ratio = w / h
    grids = sorted({(c, r) for n in range(1, max_tiles + 1) for c in range(1, n + 1) for r in range(1, n + 1)
                    if c * r <= max_tiles}, key=lambda g: g[0] * g[1])
    best = min(grids, key=lambda g: (abs(ratio - g[0] / g[1]), -g[0] * g[1]))
    cols, rows = best
    big = img.resize((SIZE * cols, SIZE * rows))
    out = [big.crop((c * SIZE, r * SIZE, (c + 1) * SIZE, (r + 1) * SIZE)) for r in range(rows) for c in range(cols)]
    if len(out) > 1:
        out.append(img.resize((SIZE, SIZE)))     # thumbnail: the whole page at once
    return out


def _pixels(img: Image.Image, max_tiles: int = MAX_TILES):
    import torch
    import torchvision.transforms as T
    tf = T.Compose([T.ToTensor(), T.Normalize(_MEAN, _STD)])
    return torch.stack([tf(t.convert("RGB")) for t in _tiles(img.convert("RGB"), max_tiles)])


_LOOP = re.compile(r"(.{1,12}?)\1{12,}")   # a short unit repeated a dozen times: decoding loop


def read(img: Image.Image, prompt: str | None = None, sparse: bool = False) -> str:
    """All text of one page image (tables as Markdown), or what `prompt` asks (charts.PROMPT). One page
    at a time: batch_chat on MPS was measured slower (27 s vs 11 s a page for 4 pages) and lost a page's
    text to the padding."""
    pv = _pixels(img, SMALL_TILES if sparse else MAX_TILES)
    with _lock:
        model, tok = _load()
        out = model.chat(tok, pv.to(_device, dtype=next(model.parameters()).dtype), "<image>\n" + (prompt or PROMPT),
                         dict(max_new_tokens=MAX_NEW_TOKENS, do_sample=False, num_beams=1, repetition_penalty=1.15))
    return _LOOP.sub(lambda m: m.group(1) * 3 + " …", out).strip()


def markdown_tables_to_text(text: str) -> str:
    """'| a | b |' rows -> 'a | b'; the separator row is dropped (same form as the other parsers)."""
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            lines.append(" | ".join(cells))
        else:
            lines.append(ln)
    return "\n".join(lines)
