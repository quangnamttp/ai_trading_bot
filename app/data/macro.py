"""Dữ liệu vĩ mô miễn phí: Fear & Greed, thanh khoản stablecoin, BTC dominance, lịch kinh tế Mỹ."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.data.http import get_json

log = logging.getLogger(__name__)


async def fear_greed_history() -> pd.Series:
    """Toàn bộ lịch sử chỉ số Fear & Greed (theo ngày)."""
    data = await get_json("https://api.alternative.me/fng/", {"limit": 0}, ttl=3600)
    rows = data["data"]
    s = pd.Series([int(r["value"]) for r in rows],
                  index=pd.to_datetime([int(r["timestamp"]) for r in rows], unit="s", utc=True))
    return s.sort_index()


async def fear_greed_now() -> tuple[int, str] | None:
    try:
        data = await get_json("https://api.alternative.me/fng/", {"limit": 1}, ttl=1800)
        r = data["data"][0]
        return int(r["value"]), r["value_classification"]
    except Exception as exc:  # noqa: BLE001
        log.warning("Fear&Greed lỗi: %s", exc)
        return None


async def stablecoin_change_7d() -> float | None:
    """% thay đổi tổng cung stablecoin 7 ngày (tiền mới vào thị trường > 0)."""
    try:
        rows = await get_json("https://stablecoins.llama.fi/stablecoincharts/all", ttl=6 * 3600)
        vals = [float(r["totalCirculatingUSD"]["peggedUSD"]) for r in rows[-8:]]
        return (vals[-1] - vals[0]) / vals[0]
    except Exception as exc:  # noqa: BLE001
        log.warning("Stablecoin supply lỗi: %s", exc)
        return None


async def btc_dominance() -> float | None:
    try:
        d = await get_json("https://api.coingecko.com/api/v3/global", ttl=1800)
        return float(d["data"]["market_cap_percentage"]["btc"])
    except Exception as exc:  # noqa: BLE001
        log.warning("BTC dominance lỗi: %s", exc)
        return None


_last_calendar: list[dict] = []


async def _save_calendar(rows: list[dict]) -> None:
    try:
        from app import storage
        await storage.kv_set("calendar_json", json.dumps(rows))
    except Exception as exc:  # noqa: BLE001
        log.debug("Không lưu được lịch: %s", exc)


async def _load_calendar() -> list[dict]:
    try:
        from app import storage
        raw = await storage.kv_get("calendar_json")
        return json.loads(raw) if raw else []
    except Exception:  # noqa: BLE001
        return []


async def us_calendar(impacts: tuple[str, ...] = ("High",)) -> list[dict]:
    """Tin kinh tế Mỹ trong tuần (ForexFactory, miễn phí) theo mức tác động.
    ForexFactory giới hạn tần suất rất chặt -> không chờ khi bị chặn, dùng bản tải thành công gần nhất."""
    global _last_calendar
    try:
        rows = await get_json("https://nfs.faireconomy.media/ff_calendar_thisweek.json", ttl=3 * 3600,
                              retries=1, max_wait=0)
        if rows is not _last_calendar:
            _last_calendar = rows
            await _save_calendar(rows)
    except Exception as exc:  # noqa: BLE001
        log.warning("Lịch kinh tế lỗi (dùng bản gần nhất): %s", exc)
        rows = _last_calendar or await _load_calendar()
    events = []
    for r in rows:
        if r.get("country") == "USD" and r.get("impact") in impacts:
            try:
                events.append({"title": r["title"], "time": datetime.fromisoformat(r["date"]).astimezone(timezone.utc),
                               "impact": r["impact"], "forecast": r.get("forecast") or "",
                               "previous": r.get("previous") or ""})
            except (KeyError, ValueError):
                continue
    return sorted(events, key=lambda e: e["time"])


async def high_impact_events() -> list[dict]:
    """Sự kiện kinh tế Mỹ tác động mạnh trong tuần (CPI, FOMC, NFP...)."""
    return await us_calendar(("High",))


async def event_blackout(now: datetime | None = None, before: timedelta = timedelta(hours=3),
                         after: timedelta = timedelta(hours=1)) -> dict | None:
    """Trả về sự kiện nếu đang trong cửa sổ cấm phát tín hiệu (3h trước -> 1h sau)."""
    now = now or datetime.now(timezone.utc)
    for ev in await high_impact_events():
        if ev["time"] - before <= now <= ev["time"] + after:
            return ev
    return None
