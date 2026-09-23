"""Cấu hình đọc từ biến môi trường (.env khi chạy local)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

VN_TZ = timezone(timedelta(hours=7))


def _ids(raw: str | None) -> list[int]:
    return [int(x) for x in (raw or "").replace(" ", "").split(",") if x.isdigit()]


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    admin_ids: list[int] = field(default_factory=lambda: _ids(os.getenv("ADMIN_IDS") or os.getenv("TELEGRAM_ADMIN_ID")))
    # Render tự cấp RENDER_EXTERNAL_URL; để trống => chạy polling (máy local)
    public_url: str = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "")
    port: int = _int("PORT", 8080)
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")

    # Vũ trụ coin
    top_n: int = _int("TOP_N", 30)
    min_quote_volume: float = _float("MIN_QUOTE_VOLUME", 20_000_000)

    # Chính sách tín hiệu
    score_threshold: float = _float("SCORE_THRESHOLD", 75)
    max_signals_per_day: int = _int("MAX_SIGNALS_PER_DAY", 5)
    max_signals_per_scan: int = _int("MAX_SIGNALS_PER_SCAN", 2)
    max_open_signals: int = _int("MAX_OPEN_SIGNALS", 6)
    max_hold_hours: int = _int("MAX_HOLD_HOURS", 7 * 24)
    default_risk_pct: float = _float("DEFAULT_RISK_PCT", 0.5)
    max_leverage: int = _int("MAX_LEVERAGE", 10)

    # Tùy chọn
    cryptopanic_token: str = os.getenv("CRYPTOPANIC_TOKEN", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
