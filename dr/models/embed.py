"""bge-m3 embeddings through the local Ollama server."""
from __future__ import annotations

import numpy as np
import httpx

from dr.config import settings
from dr.models.memo import lru

DIM = 1024


def embed_texts(texts: list[str], batch: int = 32) -> np.ndarray:
    out: list[list[float]] = []
    with httpx.Client(timeout=300) as c:
        for i in range(0, len(texts), batch):
            r = c.post(f"{settings.ollama_url}/api/embed",
                       json={"model": settings.embed_model, "keep_alive": settings.llm_keep_alive,
                             "input": [t[:4000] for t in texts[i:i + batch]]})
            r.raise_for_status()
            out.extend(r.json()["embeddings"])
    if not out:
        return np.zeros((0, DIM), dtype=np.float32)
    m = np.asarray(out, dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    return m


@lru(4096)
def embed_query(text: str) -> np.ndarray:
    return embed_texts([text])[0]
