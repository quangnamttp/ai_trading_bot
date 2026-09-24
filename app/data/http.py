"""HTTP client dùng chung: retry, fallback host, cache TTL trong bộ nhớ."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_loop: asyncio.AbstractEventLoop | None = None
_sem: asyncio.Semaphore | None = None
_cache: dict[str, tuple[float, Any]] = {}


def client() -> httpx.AsyncClient:
    """Client dùng chung; tạo lại nếu event loop đổi (vd test / script gọi asyncio.run nhiều lần)."""
    global _client, _loop, _sem
    loop = asyncio.get_running_loop()
    if _loop is not loop:
        _client, _loop, _sem = None, loop, asyncio.Semaphore(8)
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (signal-bot)"},
        )
    return _client


async def close() -> None:
    if _client is not None:
        await _client.aclose()


async def get_json(urls: str | list[str], params: dict | None = None, *, ttl: float = 0, retries: int = 3,
                   max_wait: float = 120) -> Any:
    """GET JSON, thử lần lượt các host dự phòng. `ttl` > 0 để cache kết quả."""
    urls = [urls] if isinstance(urls, str) else urls
    key = f"{urls[0]}?{sorted((params or {}).items())}"
    if ttl and key in _cache and _cache[key][0] > time.time():
        return _cache[key][1]

    last_exc: Exception | None = None
    for attempt in range(retries):
        for url in urls:
            try:
                c = client()
                async with _sem:
                    r = await c.get(url, params=params)
                if r.status_code in (418, 429):  # quá giới hạn tần suất -> chờ đúng thời gian sàn yêu cầu
                    wait = min(float(r.headers.get("Retry-After", 30)), max_wait)
                    log.warning("Bị giới hạn tần suất %s, chờ %.0fs", url, wait)
                    await asyncio.sleep(wait)
                    raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                data = r.json()
                if ttl:
                    _cache[key] = (time.time() + ttl, data)
                return data
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                log.debug("GET %s failed: %s", url, exc)
        await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {urls[0]} failed: {last_exc}")


async def get_text(url: str, *, ttl: float = 0) -> str:
    if ttl and url in _cache and _cache[url][0] > time.time():
        return _cache[url][1]
    c = client()
    async with _sem:
        r = await c.get(url)
    r.raise_for_status()
    if ttl:
        _cache[url] = (time.time() + ttl, r.text)
    return r.text
