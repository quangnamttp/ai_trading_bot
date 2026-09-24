"""Điểm khởi chạy: 1 event loop, 1 web server (aiohttp) cho webhook Telegram + health check.

- Có PUBLIC_URL / RENDER_EXTERNAL_URL -> chế độ webhook (Render).
- Không có -> chế độ polling (chạy trên máy cá nhân).
UptimeRobot ping GET/HEAD `/` hoặc `/health` mỗi 5 phút để Render free không ngủ.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import signal
from datetime import datetime, time, timedelta, timezone

from aiohttp import web
from telegram import Update
from telegram.ext import Application, ContextTypes

from app import reports, service, storage
from app.bot import handlers
from app.config import VN_TZ, settings
from app.data import binance, http

log = logging.getLogger("app")
STARTED = datetime.now(VN_TZ)


# ---------------------------------------------------------------- jobs
async def job_scan(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Mỗi giờ (1'30" sau khi nến 1H đóng): swing ngắn; thêm swing dài khi nến 4H vừa đóng."""
    styles = ("short", "long") if datetime.now(timezone.utc).hour % 4 == 0 else ("short",)
    try:
        await service.run_scan(ctx.bot, styles)
    except Exception:  # noqa: BLE001
        log.exception("Quét lỗi")


async def _safe(name: str, coro) -> None:
    try:
        await coro
    except Exception:  # noqa: BLE001
        log.exception("Job %s lỗi", name)


async def job_track(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _safe("track", service.track(ctx.bot))


async def job_morning(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _safe("morning", reports.morning(ctx.bot))


async def job_watch(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _safe("watch", reports.afternoon_watch(ctx.bot))


async def job_evening(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _safe("evening", reports.evening(ctx.bot))


async def job_news(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _safe("news", reports.news_alerts(ctx.bot))


async def job_macro(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _safe("macro", reports.macro_reminders(ctx.bot))


async def job_health(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _safe("health", reports.health_check(ctx.bot))


def schedule(app: Application) -> None:
    jq = app.job_queue
    now = datetime.now(VN_TZ)
    next_scan = (now + timedelta(hours=1)).replace(minute=1, second=30, microsecond=0)  # 1'30" sau khi nến 1H đóng
    jq.run_repeating(job_scan, interval=3600, first=next_scan, name="scan")
    jq.run_repeating(job_track, interval=300, first=30, name="track")
    jq.run_repeating(job_news, interval=900, first=120, name="news")
    jq.run_repeating(job_macro, interval=600, first=60, name="macro")
    jq.run_repeating(job_health, interval=1800, first=600, name="health")
    jq.run_daily(job_morning, time=time(7, 0, tzinfo=VN_TZ), name="morning")
    jq.run_daily(job_watch, time=time(settings.watch_report_hour, 5, tzinfo=VN_TZ), name="watch")
    jq.run_daily(job_evening, time=time(settings.quiet_start, 0, tzinfo=VN_TZ), name="evening")


# ---------------------------------------------------------------- web
def webhook_secret() -> str:
    """Telegram chỉ nhận A-Z a-z 0-9 _ - (tối đa 256 ký tự); secret do Render sinh ra có thể chứa ký tự khác
    -> luôn băm về chuỗi hex hợp lệ."""
    seed = settings.webhook_secret or settings.telegram_token
    return hashlib.sha256(seed.encode()).hexdigest()[:48]


def make_web(app: Application) -> web.Application:
    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True, "started": STARTED.isoformat()})

    async def telegram_hook(request: web.Request) -> web.Response:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != webhook_secret():
            return web.Response(status=403)
        await app.update_queue.put(Update.de_json(await request.json(), app.bot))
        return web.Response(text="ok")

    w = web.Application()
    w.router.add_get("/", health)
    w.router.add_get("/health", health)
    w.router.add_post("/telegram", telegram_hook)
    return w


async def run() -> None:
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not settings.telegram_token:
        raise SystemExit("Thiếu TELEGRAM_BOT_TOKEN")

    await storage.init()
    builder = Application.builder().token(settings.telegram_token)
    if settings.public_url:
        builder = builder.updater(None)
    app = builder.build()
    handlers.register(app)
    schedule(app)

    runner = web.AppRunner(make_web(app))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", settings.port).start()
    log.info("Web server chạy ở cổng %s", settings.port)

    async with app:
        await app.start()
        try:
            await _serve(app)
        finally:
            if app.updater and app.updater.running:
                await app.updater.stop()
            if app.running:
                await app.stop()
    await runner.cleanup()
    await http.close()


async def _serve(app: Application) -> None:
    """Đặt webhook/polling, báo admin, rồi chờ tới khi nhận tín hiệu tắt."""
    if settings.public_url:
        await app.bot.set_webhook(f"{settings.public_url}/telegram", secret_token=webhook_secret(),
                                  allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        log.info("Webhook: %s/telegram", settings.public_url)
    else:
        await app.bot.delete_webhook()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        log.info("Chạy chế độ polling (local)")
    status = f"✅ Bot đã khởi động lúc {STARTED:%H:%M %d/%m}"
    try:
        await binance.last_price("BTCUSDT")
    except Exception as exc:  # noqa: BLE001
        # thường gặp: HTTP 451 khi server đặt ở vùng Binance chặn (Mỹ...)
        log.error("Không gọi được Binance: %s", exc)
        status += (f"\n⚠️ KHÔNG lấy được dữ liệu Binance ({exc}).\n"
                   "Nếu lỗi 451: vùng server bị Binance chặn — tạo lại service Render ở region Frankfurt.")
    for admin in settings.admin_ids:
        try:
            await app.bot.send_message(admin, status)
        except Exception:  # noqa: BLE001
            log.warning("Không gửi được tin khởi động cho admin %s", admin)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            signal.signal(sig, lambda *_: stop.set())
    await stop.wait()
    log.info("Đang tắt...")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
