"""HTTP client dùng chung: retry, fallback host, cache TTL trong bộ nhớ.

Chống kẹt khi sàn giới hạn tần suất (HTTP 429/418 — Render miễn phí dùng chung IP với nhiều người):
- KHÔNG đứng chờ: đánh dấu host đó "tạm nghỉ" theo Retry-After và báo lỗi ngay để nơi gọi chuyển nguồn (Bybit...).
- Trong thời gian tạm nghỉ, mọi lệnh gọi tới host đó bị từ chối ngay, không gửi thêm request (tránh bị chặn nặng hơn).
- Dữ liệu có cache mà gọi lỗi -> trả bản cũ gần nhất (vẫn tốt hơn là không có gì).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_loop: asyncio.AbstractEventLoop | None = None
_sem: asyncio.Semaphore | None = None
_cache: dict[str, tuple[float, Any]] = {}
_blocked_until: dict[str, float] = {}  # host -> thời điểm hết tạm nghỉ
last_block: dict[str, float] = {}      # host -> lần gần nhất bị giới hạn (để báo admin)
STALE_MAX = 6 * 3600                   # bản cache cũ tối đa 6 giờ vẫn được dùng khi gọi lỗi


class RateLimited(RuntimeError):
    """Host đang bị sàn giới hạn tần suất."""


def client() -> httpx.AsyncClient:
    """Client dùng chung; tạo lại nếu event loop đổi (vd test / script gọi asyncio.run nhiều lần)."""
    global _client, _loop, _sem
    loop = asyncio.get_running_loop()
    if _loop is not loop:
        _client, _loop, _sem = None, loop, asyncio.Semaphore(8)
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=6.0),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (signal-bot)"},
        )
    return _client


async def close() -> None:
    if _client is not None:
        await _client.aclose()


def _host(url: str) -> str:
    return urlsplit(url).netloc


def blocked(url: str) -> bool:
    return _blocked_until.get(_host(url), 0) > time.time()


async def get_json(urls: str | list[str], params: dict | None = None, *, ttl: float = 0, retries: int = 2,
                   max_wait: float = 0) -> Any:
    """GET JSON, thử lần lượt các host dự phòng. `ttl` > 0 để cache kết quả.
    `max_wait` giữ lại cho tương thích (không còn đứng chờ khi bị giới hạn tần suất)."""
    urls = [urls] if isinstance(urls, str) else urls
    key = f"{urls[0]}?{sorted((params or {}).items())}"
    cached = _cache.get(key)
    if ttl and cached and cached[0] > time.time():
        return cached[1]

    last_exc: Exception | None = None
    for attempt in range(retries):
        live = [u for u in urls if not blocked(u)]
        if not live:
            last_exc = RateLimited(f"{_host(urls[0])} đang bị giới hạn tần suất")
            break
        for url in live:
            try:
                c = client()
                async with _sem:
                    r = await c.get(url, params=params)
                if r.status_code in (418, 429):
                    pause = min(max(float(r.headers.get("Retry-After", 60)), 30), 600)
                    host = _host(url)
                    _blocked_until[host] = time.time() + pause
                    last_block[host] = time.time()
                    log.warning("Bị giới hạn tần suất %s (HTTP %s) -> tạm nghỉ host %.0fs, chuyển nguồn dự phòng",
                                host, r.status_code, pause)
                    last_exc = RateLimited(f"{host} HTTP {r.status_code}")
                    continue
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
        if isinstance(last_exc, RateLimited):
            break
        await asyncio.sleep(1.0 * (attempt + 1))
    if cached and cached[0] + STALE_MAX > time.time():
        log.info("Dùng dữ liệu cache cũ cho %s (%s)", urls[0], last_exc)
        return cached[1]
    if isinstance(last_exc, RateLimited):
        raise last_exc
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
