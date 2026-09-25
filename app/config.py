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
    news_bot_token: str = os.getenv("NEWS_BOT_TOKEN", "")  # 📰 Bot Tin tức (tùy chọn, chạy chung service)
    admin_ids: list[int] = field(default_factory=lambda: _ids(os.getenv("ADMIN_IDS") or os.getenv("TELEGRAM_ADMIN_ID")))
    # Render tự cấp RENDER_EXTERNAL_URL; để trống => chạy polling (máy local)
    public_url: str = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "")
    port: int = _int("PORT", 8080)
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")

    # Vũ trụ coin
    top_n: int = _int("TOP_N", 20)
    min_quote_volume: float = _float("MIN_QUOTE_VOLUME", 20_000_000)
    min_listing_days: int = _int("MIN_LISTING_DAYS", 90)  # bỏ coin mới niêm yết (hay bơm xả thất thường)

    # Chính sách tín hiệu — Swing ngắn (1H/4H/1D)
    score_threshold: float = _float("SCORE_THRESHOLD", 75)
    max_signals_per_day: int = _int("MAX_SIGNALS_PER_DAY", 3)
    max_signals_per_scan: int = _int("MAX_SIGNALS_PER_SCAN", 2)
    max_open_signals: int = _int("MAX_OPEN_SIGNALS", 6)
    max_same_direction: int = _int("MAX_SAME_DIRECTION", 2)  # tối đa lệnh cùng chiều mở cùng lúc
    max_hold_hours: int = _int("MAX_HOLD_HOURS", 7 * 24)
    default_risk_pct: float = _float("DEFAULT_RISK_PCT", 0.5)
    max_leverage: int = _int("MAX_LEVERAGE", 10)

    # Swing dài (4H/1D/1W)
    long_max_per_week: int = _int("LONG_MAX_PER_WEEK", 3)
    long_max_hold_hours: int = _int("LONG_MAX_HOLD_HOURS", 30 * 24)
    long_max_leverage: int = _int("LONG_MAX_LEVERAGE", 5)

    # Giờ yên lặng (giờ VN): không gửi tín hiệu MỚI, vẫn báo SL/TP lệnh đang chạy
    quiet_start: int = _int("QUIET_START", 22)
    quiet_end: int = _int("QUIET_END", 6)
    watch_report_hour: int = _int("WATCH_REPORT_HOUR", 15)  # chưa có tín hiệu tới giờ này -> gửi danh sách theo dõi
    health_alert_hours: float = _float("HEALTH_ALERT_HOURS", 3)

    # Người dùng
    private_mode: bool = os.getenv("PRIVATE_MODE", "1") == "1"   # người mới phải được admin duyệt
    max_user_coins: int = _int("MAX_USER_COINS", 20)

    # AI hỏi đáp (tùy chọn; thử lần lượt Gemini -> Groq -> OpenRouter, lỗi hết thì trả lời bằng dữ liệu có sẵn)
    gemini_key: str = os.getenv("GEMINI_API_KEY", "")
    groq_key: str = os.getenv("GROQ_API_KEY", "")
    openrouter_key: str = os.getenv("OPENROUTER_API_KEY", "")
    ai_daily_limit: int = _int("AI_DAILY_LIMIT", 50)            # câu hỏi AI / người / ngày ở Bot Tín hiệu
    ai_news_daily_limit: int = _int("AI_NEWS_DAILY_LIMIT", 100)  # ... ở Bot Tin tức

    # Cảnh báo thị trường
    btc_move_alert_pct: float = _float("BTC_MOVE_ALERT_PCT", 3.0)       # BTC chạy >= x% trong 1 giờ
    funding_alert: float = _float("FUNDING_ALERT", 0.001)               # |funding| >= 0.1%/8h
    move_1h_pct: float = _float("MOVE_1H_PCT", 5.0)     # 🚀 coin chạy >= x% trong ~1 giờ
    move_4h_pct: float = _float("MOVE_4H_PCT", 10.0)    # ... hoặc >= y% trong ~4 giờ
    move_vol_x: float = _float("MOVE_VOL_X", 2.5)       # kèm volume >= z lần trung bình

    # Tùy chọn
    cryptopanic_token: str = os.getenv("CRYPTOPANIC_TOKEN", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
