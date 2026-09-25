"""Điểm khởi chạy: 1 event loop, 1 web server (aiohttp) cho webhook Telegram + health check.

- Có PUBLIC_URL / RENDER_EXTERNAL_URL -> chế độ webhook (Render).
- Không có -> chế độ polling (chạy trên máy cá nhân).
UptimeRobot ping GET/HEAD `/` hoặc `/health` mỗi 5 phút để Render free không ngủ.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
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
HEARTBEAT: dict[str, datetime] = {}  # việc định kỳ -> lần chạy xong gần nhất (tự phục hồi khi kẹt)


def beat(name: str) -> None:
    HEARTBEAT[name] = datetime.now(timezone.utc)


async def job_watchdog(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Tự phục hồi: quét (mỗi giờ) hoặc theo dõi lệnh (mỗi 5 phút) không chạy xong quá lâu -> báo admin rồi thoát
    tiến trình; Render tự khởi động lại bot sau khoảng 1 phút (không cần ai vào sửa tay)."""
    now = datetime.now(timezone.utc)
    limits = {"scan": timedelta(hours=2, minutes=30), "track": timedelta(minutes=40)}
    stuck = [n for n, lim in limits.items() if now - HEARTBEAT.get(n, STARTED) > lim]
    if not stuck:
        return
    msg = f"♻️ Việc {', '.join(stuck)} bị kẹt quá lâu → bot tự khởi động lại."
    log.error(msg)
    try:
        await service.notify_admins(ctx.bot, msg)
    finally:
        os._exit(1)


async def job_health_daily(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _safe("health_daily", reports.daily_health(ctx.bot))


async def job_backup(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if datetime.now(VN_TZ).weekday() == 6:  # tối chủ nhật: gửi file sao lưu cho admin
        await _safe("backup", reports.send_backup(ctx.bot))


async def job_scan(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Mỗi giờ (1'30" sau khi nến 1H đóng): swing ngắn; thêm swing dài khi nến 4H vừa đóng."""
    styles = ("short", "long") if datetime.now(timezone.utc).hour % 4 == 0 else ("short",)
    try:
        await service.run_scan(ctx.bot, styles)
    except Exception:  # noqa: BLE001
        log.exception("Quét lỗi")
    # 🎯 tín hiệu chỉ báo cho coin tự chọn: 1H mỗi giờ, 4H khi nến 4H vừa đóng
    for tf in ("1h", "4h") if datetime.now(timezone.utc).hour % 4 == 0 else ("1h",):
        try:
            log.info(await asyncio.wait_for(service.run_indicator(ctx.bot, tf), 240))
        except Exception:  # noqa: BLE001
            log.exception("Chỉ báo %s lỗi", tf)
    beat("scan")


async def _safe(name: str, coro) -> None:
    try:
        await coro
    except Exception:  # noqa: BLE001
        log.exception("Job %s lỗi", name)


async def job_track(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _safe("track", asyncio.wait_for(service.track(ctx.bot), 240))
    beat("track")


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


async def job_alerts(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from app import alerts
    await _safe("alerts", reports.market_alerts(ctx.bot))
    await _safe("moves", reports.big_moves(ctx.bot))
    await _safe("breaking", alerts.breaking_news(ctx.bot))


async def job_listings(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from app import alerts
    await _safe("listings", alerts.listings(ctx.bot))


async def job_early(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Mỗi giờ (sau khi nến 1H đóng): dấu hiệu gom hàng / ép short + dòng tiền stablecoin."""
    from app import alerts
    await _safe("early", asyncio.wait_for(alerts.early_signals(ctx.bot), 300))
    await _safe("money", alerts.stablecoin_flow(ctx.bot))


async def job_holdings(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _safe("holdings", reports.holdings_watch(ctx.bot))


async def job_dca(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from app.bot import portfolio_ui
    await _safe("dca", portfolio_ui.dca_watch(ctx.bot))


async def job_weekly_market(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if datetime.now(VN_TZ).weekday() == 6:  # chủ nhật: tổng kết thị trường tuần vào topic 📰
        await _safe("weekly_market", reports.weekly_market(ctx.bot))


async def job_weekly(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if datetime.now(VN_TZ).weekday() == 6:  # chủ nhật
        await _safe("weekly", reports.weekly_report(ctx.bot))


def schedule(app: Application) -> None:
    jq = app.job_queue
    now = datetime.now(VN_TZ)
    next_scan = (now + timedelta(hours=1)).replace(minute=1, second=30, microsecond=0)  # 1'30" sau khi nến 1H đóng
    jq.run_repeating(job_scan, interval=3600, first=next_scan, name="scan")
    jq.run_repeating(job_track, interval=300, first=30, name="track")
    jq.run_repeating(job_news, interval=900, first=120, name="news")
    jq.run_repeating(job_macro, interval=300, first=60, name="macro")
    jq.run_repeating(job_health, interval=1800, first=600, name="health")
    jq.run_daily(job_morning, time=time(7, 0, tzinfo=VN_TZ), name="morning")
    jq.run_daily(job_watch, time=time(settings.watch_report_hour, 5, tzinfo=VN_TZ), name="watch")
    jq.run_daily(job_evening, time=time(settings.quiet_start, 0, tzinfo=VN_TZ), name="evening")
    jq.run_daily(job_weekly_market, time=time(20, 0, tzinfo=VN_TZ), name="weekly_market")
    jq.run_daily(job_weekly, time=time(settings.quiet_start, 5, tzinfo=VN_TZ), name="weekly")
    jq.run_repeating(job_alerts, interval=900, first=180, name="alerts")
    jq.run_repeating(job_dca, interval=900, first=240, name="dca")
    jq.run_repeating(job_holdings, interval=3600, first=next_scan + timedelta(minutes=4), name="holdings")
    jq.run_repeating(job_watchdog, interval=600, first=900, name="watchdog")
    jq.run_repeating(job_listings, interval=300, first=90, name="listings")
    jq.run_repeating(job_early, interval=3600, first=next_scan + timedelta(minutes=6), name="early")
    jq.run_daily(job_backup, time=time(23, 30, tzinfo=VN_TZ), name="backup")
    jq.run_daily(job_health_daily, time=time(23, 0, tzinfo=VN_TZ), name="health_daily")


# ---------------------------------------------------------------- web
def webhook_secret(token: str | None = None) -> str:
    """Telegram chỉ nhận A-Z a-z 0-9 _ - (tối đa 256 ký tự); secret do Render sinh ra có thể chứa ký tự khác
    -> luôn băm về chuỗi hex hợp lệ. Bot Tin tức dùng secret riêng (băm từ token của nó)."""
    seed = (settings.webhook_secret or settings.telegram_token) + (token or "")
    return hashlib.sha256(seed.encode()).hexdigest()[:48]


def make_web(app: Application, news_app: Application | None = None) -> web.Application:
    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True, "started": STARTED.isoformat()})

    async def telegram_hook(request: web.Request) -> web.Response:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != webhook_secret():
            return web.Response(status=403)
        await app.update_queue.put(Update.de_json(await request.json(), app.bot))
        return web.Response(text="ok")

    async def news_hook(request: web.Request) -> web.Response:
        if news_app is None or request.headers.get("X-Telegram-Bot-Api-Secret-Token") != webhook_secret(settings.news_bot_token):
            return web.Response(status=403)
        await news_app.update_queue.put(Update.de_json(await request.json(), news_app.bot))
        return web.Response(text="ok")

    w = web.Application()
    w.router.add_get("/", health)
    w.router.add_get("/health", health)
    w.router.add_post("/telegram", telegram_hook)
    w.router.add_post("/telegram-news", news_hook)
    return w


async def run() -> None:
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not settings.telegram_token:
        raise SystemExit("Thiếu TELEGRAM_BOT_TOKEN")

    await storage.init()
    # concurrent_updates: 1 người hỏi AI (vài giây) không bắt người khác phải chờ
    builder = Application.builder().token(settings.telegram_token).concurrent_updates(True)
    if settings.public_url:
        builder = builder.updater(None)
    app = builder.build()
    handlers.register(app)
    schedule(app)
    news_app = None
    if settings.news_bot_token:
        from app.bot import news
        nb = Application.builder().token(settings.news_bot_token).concurrent_updates(True)
        if settings.public_url:
            nb = nb.updater(None)
        news_app = nb.build()
        news.register(news_app)

    runner = web.AppRunner(make_web(app, news_app))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", settings.port).start()
    log.info("Web server chạy ở cổng %s", settings.port)

    async with app:
        await app.start()
        if news_app:
            await news_app.initialize()
            await news_app.start()
        try:
            await _serve(app, news_app)
        finally:
            for a in (news_app, app):
                if a is None:
                    continue
                if a.updater and a.updater.running:
                    await a.updater.stop()
                if a.running:
                    await a.stop()
            if news_app:
                await news_app.shutdown()
    await runner.cleanup()
    await http.close()


async def set_commands(app: Application) -> None:
    """Không dùng danh sách lệnh "/" -> Telegram ẩn nút ☰ Menu; mọi chức năng nằm trong bàn phím nút
    (admin có thêm 👥 Quản lý). Lệnh cũ vẫn gõ tay được."""
    from telegram import (BotCommandScopeAllChatAdministrators, BotCommandScopeAllGroupChats,
                          BotCommandScopeAllPrivateChats, BotCommandScopeChat, BotCommandScopeDefault, MenuButtonDefault)
    scopes = [BotCommandScopeDefault(), BotCommandScopeAllPrivateChats(), BotCommandScopeAllGroupChats(),
              BotCommandScopeAllChatAdministrators()] + [BotCommandScopeChat(a) for a in settings.admin_ids]
    for scope in scopes:
        try:
            await app.bot.delete_my_commands(scope=scope)
        except Exception as exc:  # noqa: BLE001
            log.debug("Xóa danh sách lệnh %s lỗi: %s", scope, exc)
    try:
        await app.bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    except Exception as exc:  # noqa: BLE001
        log.debug("Đặt nút menu lỗi: %s", exc)


async def _serve(app: Application, news_app: Application | None = None) -> None:
    """Đặt webhook/polling cho Bot Tín hiệu (+ Bot Tin tức nếu có), báo admin, rồi chờ tới khi nhận tín hiệu tắt."""
    for a, path, secret in ((app, "/telegram", webhook_secret()),
                            (news_app, "/telegram-news", webhook_secret(settings.news_bot_token))):
        if a is None:
            continue
        if settings.public_url:
            await a.bot.set_webhook(f"{settings.public_url}{path}", secret_token=secret,
                                    allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
            log.info("Webhook: %s%s", settings.public_url, path)
        else:
            await a.bot.delete_webhook()
            await a.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
            log.info("Chạy chế độ polling (local) %s", path)
        await set_commands(a)
    reports.SIGNAL_BOT = app.bot
    reports.SIGNAL_USERNAME = (await app.bot.get_me()).username or ""
    if news_app:
        reports.NEWS_BOT = news_app.bot
        reports.NEWS_USERNAME = (await news_app.bot.get_me()).username or ""
        from app.bot import news
        await news.refresh_menus(news_app.bot)
    await handlers.refresh_menus(app.bot)
    status = f"✅ Bot đã khởi động lúc {STARTED:%H:%M %d/%m}" + (
        f" · 📰 Bot Tin tức @{reports.NEWS_USERNAME} đang chạy" if news_app else " · chưa có NEWS_BOT_TOKEN (tin tức gửi qua bot này)")
    try:
        await binance.last_price("BTCUSDT")
    except Exception as exc:  # noqa: BLE001
        # thường gặp: HTTP 451 khi server đặt ở vùng Binance chặn (Mỹ...)
        log.error("Không gọi được Binance: %s", exc)
        status += (f"\n⚠️ KHÔNG lấy được dữ liệu Binance ({exc}).\n"
                   "Nếu lỗi 451: vùng server bị Binance chặn — tạo lại service Render ở region Frankfurt.")
    await service.notify_admins(app.bot, status)  # vào topic nhật ký (không có thì nhắn riêng admin)

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
