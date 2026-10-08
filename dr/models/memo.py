"""Small thread-safe LRU for pure model calls (same input -> same output), so a repeated
question skips the reranker, NLI and query embedding as well as the LLM."""
from __future__ import annotations

import functools
import hashlib
import pickle
import threading
from collections import OrderedDict


def lru(size: int = 4096):
    def deco(fn):
        cache: OrderedDict[str, object] = OrderedDict()
        lock = threading.Lock()

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            k = hashlib.sha256(pickle.dumps((args, sorted(kwargs.items())))).hexdigest()
            with lock:
                if k in cache:
                    cache.move_to_end(k)
                    return pickle.loads(cache[k])
            out = fn(*args, **kwargs)
            with lock:
                cache[k] = pickle.dumps(out)
                while len(cache) > size:
                    cache.popitem(last=False)
            return out
        wrapper.cache_clear = cache.clear
        return wrapper
    return deco
