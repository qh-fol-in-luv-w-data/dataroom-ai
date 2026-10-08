"""Cross-encoder reranker: BAAI/bge-reranker-v2-m3 (multilingual, includes Vietnamese)."""
from __future__ import annotations

import threading

from dr.config import settings
from dr.models.memo import lru

_model = None
_lock = threading.Lock()


def _device() -> str:
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def get():
    global _model
    with _lock:
        if _model is None:
            from sentence_transformers import CrossEncoder
            _model = CrossEncoder(settings.rerank_model, max_length=512, device=_device())
    return _model


@lru(2048)
def rerank(query: str, passages: list[str]) -> list[float]:
    if not passages:
        return []
    m = get()
    with _lock:
        scores = m.predict([(query, p) for p in passages], batch_size=8, show_progress_bar=False)
    return [float(s) for s in scores]
