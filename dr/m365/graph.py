"""Minimal Microsoft Graph / SharePoint REST client: paging, delta, $batch, throttling."""
from __future__ import annotations

import logging
import time
from typing import Callable, Iterator

import httpx

log = logging.getLogger("graph")
GRAPH = "https://graph.microsoft.com/v1.0"
RETRY = {429, 503, 504}


class GraphError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"{status} {url}: {body[:300]}")
        self.status, self.body, self.url = status, body, url


class Graph:
    def __init__(self, token: Callable[[], str], http: httpx.Client | None = None, base: str = GRAPH,
                 max_retries: int = 5, sleep: Callable[[float], None] = time.sleep):
        self.token = token
        self.http = http or httpx.Client(timeout=60, follow_redirects=True)
        self.base = base.rstrip("/")
        self.max_retries = max_retries
        self.sleep = sleep
        self.throttled = 0           # 429/503 seen (reported by the probe)

    def url(self, path: str) -> str:
        return path if path.startswith("http") else f"{self.base}/{path.lstrip('/')}"

    def request(self, method: str, path: str, *, token: str | None = None, headers: dict | None = None,
                **kw) -> httpx.Response:
        url = self.url(path)
        for attempt in range(self.max_retries + 1):
            h = {"Authorization": f"Bearer {token or self.token()}", **(headers or {})}
            r = self.http.request(method, url, headers=h, **kw)
            if r.status_code in RETRY and attempt < self.max_retries:
                self.throttled += 1
                wait = min(float(r.headers.get("Retry-After", 2 ** attempt)), 60.0)
                log.warning("graph %s %s → %s, retry in %.0fs", method, url, r.status_code, wait)
                self.sleep(wait)
                continue
            return r
        return r

    def get(self, path: str, *, token: str | None = None, ok: tuple = (200,), **kw) -> dict:
        r = self.request("GET", path, token=token, **kw)
        if r.status_code not in ok:
            raise GraphError(r.status_code, r.text, self.url(path))
        return r.json() if r.content else {}

    def pages(self, path: str, *, token: str | None = None, headers: dict | None = None,
              params: dict | None = None) -> Iterator[dict]:
        """Every object across @odata.nextLink pages."""
        url: str | None = path
        while url:
            d = self.get(url, token=token, headers=headers, params=params)
            params = None                       # nextLink already carries the query
            yield from d.get("value", [])
            url = d.get("@odata.nextLink")

    def delta(self, path_or_link: str, *, token: str | None = None, headers: dict | None = None,
              params: dict | None = None) -> tuple[list[dict], str]:
        """All changes since the link; returns (objects, new deltaLink)."""
        out, url = [], path_or_link
        while True:
            d = self.get(url, token=token, headers=headers, params=params)
            params = None
            out.extend(d.get("value", []))
            if "@odata.nextLink" in d:
                url = d["@odata.nextLink"]
            elif "@odata.deltaLink" in d:
                return out, d["@odata.deltaLink"]
            else:
                raise GraphError(200, "delta response without nextLink/deltaLink", self.url(url))

    def batch(self, requests: list[dict], *, token: str | None = None) -> dict[str, dict]:
        """JSON $batch in chunks of 20; returns id -> {status, body}."""
        out: dict[str, dict] = {}
        for i in range(0, len(requests), 20):
            r = self.request("POST", "$batch", token=token, json={"requests": requests[i:i + 20]})
            if r.status_code != 200:
                raise GraphError(r.status_code, r.text, self.url("$batch"))
            for resp in r.json().get("responses", []):
                out[str(resp["id"])] = {"status": resp["status"], "body": resp.get("body")}
        return out
