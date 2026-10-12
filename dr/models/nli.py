"""Multilingual NLI (mDeBERTa-v3 xnli, includes Vietnamese): P(premise entails hypothesis).

Used only as a secondary grounding signal; the deterministic quote/number checks are the
hard gate (master plan §6.5).
"""
from __future__ import annotations

import threading

from dr.config import settings
from dr.models.memo import lru

_tok = _model = None
_entail_idx = 0
_lock = threading.Lock()


def _load():
    global _tok, _model, _entail_idx
    if _model is None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        _tok = AutoTokenizer.from_pretrained(settings.nli_model)
        _model = AutoModelForSequenceClassification.from_pretrained(settings.nli_model)
        _model.eval()
        if torch.backends.mps.is_available():
            _model.to("mps")
        labels = {v.lower(): k for k, v in _model.config.id2label.items()}
        _entail_idx = labels.get("entailment", 0)


@lru(8192)
def entail(premise: str, hypothesis: str) -> float:
    import torch
    with _lock:
        _load()
        enc = _tok(premise[:2000], hypothesis[:500], truncation=True, max_length=512, return_tensors="pt")
        enc = {k: v.to(_model.device) for k, v in enc.items()}
        with torch.no_grad():
            probs = torch.softmax(_model(**enc).logits[0].float(), -1)
        return float(probs[_entail_idx])


def entail_many(pairs: list[tuple[str, str]]) -> list[float]:
    """entail() for several (premise, hypothesis) pairs in one batch (one forward pass on the GPU)."""
    import torch
    if not pairs:
        return []
    with _lock:
        _load()
        enc = _tok([pr[:2000] for pr, _ in pairs], [h[:500] for _, h in pairs], truncation=True, max_length=512,
                   padding=True, return_tensors="pt")
        enc = {k: v.to(_model.device) for k, v in enc.items()}
        with torch.no_grad():
            probs = torch.softmax(_model(**enc).logits.float(), -1)
        return [float(x) for x in probs[:, _entail_idx]]
