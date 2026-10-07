"""Per-user question limits and a cap on concurrent LLM work (availability, D12).

Sliding windows per principal (default 8 questions / minute, 60 / hour) plus a global
semaphore so a burst from one user cannot queue the local GPU for everyone else.
In production this moves to the API gateway / Redis; the policy stays the same.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from dr.config import settings


class RateLimiter:
    def __init__(self, per_minute: int | None = None, per_hour: int | None = None, concurrent: int | None = None):
        self.per_minute = per_minute or settings.rate_per_minute
        self.per_hour = per_hour or settings.rate_per_hour
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(concurrent or settings.llm_concurrency)

    def check(self, oid: str, now: float | None = None) -> float:
        """0 when allowed (and counted), else seconds to wait."""
        now = time.time() if now is None else now
        with self._lock:
            q = self._hits[oid]
            while q and now - q[0] > 3600:
                q.popleft()
            last_min = sum(1 for t in q if now - t <= 60)
            if last_min >= self.per_minute:
                return 60 - (now - [t for t in q if now - t <= 60][0])
            if len(q) >= self.per_hour:
                return 3600 - (now - q[0])
            q.append(now)
            return 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
