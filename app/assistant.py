"""Trợ lý hỏi đáp: gom dữ liệu thật của bot làm ngữ cảnh cho AI; AI lỗi thì trả lời bằng dữ liệu có sẵn."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from html import escape

from app import ai, events, storage
from app.config import VN_TZ, settings
from app.data import binance, macro, news

log = logging.getLogger(__name__)


async def market_context() -> str:
    lines = []
    try:
        tick = await binance.tickers_24h()
        for sym in ("BTCUSDT", "ETHUSDT"):
            t = tick.get(sym)
            if t:
                lines.append(f"{sym[:3]}: {float(t['lastPrice']):.2f} USD ({float(t['priceChangePercent']):+.2f}% 24h)")
        fg = await macro.fear_greed_now()
        if fg:
            lines.append(f"Fear & Greed: {fg[0]} ({fg[1]})")
        f = await binance.all_funding()
        if "BTCUSDT" in f:
            lines.append(f"Funding BTC: {f['BTCUSDT']:.4%}/8h")
    except Exception as exc:  # noqa: BLE001
        log.debug("market ctx: %s", exc)
    evs = await events.week_events()
    if evs:
        lines.append("Lịch kinh tế Mỹ tuần này (giờ VN):")
        for e in evs[:15]:
            lines.append(f"- {e['time'].astimezone(VN_TZ):%a %d/%m %H:%M} {e['title']} (tác động {e.get('impact')}, "
                         f"dự báo {e.get('forecast') or '?'}, kỳ trước {e.get('previous') or '?'})")
    items = await news.headlines(24)
    if items:
        lines.append("Tin crypto 24h gần nhất:")
        lines += [f"- {h.title}" for h in items[:10]]
    opened = await storage.open_signals()
    if opened:
        lines.append("Lệnh bot đang theo dõi: " + ", ".join(
            f"{s['display']} {'LONG' if s['side'] > 0 else 'SHORT'} từ {s['entry']:.6g}" for s in opened))
    lines.append(f"Thời gian hiện tại: {datetime.now(VN_TZ):%H:%M %d/%m/%Y} (giờ VN)")
    return "\n".join(lines)


async def _event_context(question: str) -> str:
    """Nếu câu hỏi nhắc tới một loại tin (CPI, FOMC...) -> thêm giải thích + thống kê phản ứng BTC thật."""
    kind, explain = events.classify(question)
    if kind == "other":
        return ""
    st = await events.reaction_stats(kind)
    stat = re.sub(r"<[^>]+>", "", events.stats_text(st))
    return f"\nKiến thức của bot về loại tin này:\n{explain}\n{stat}"


async def allowed(user_id: int) -> tuple[bool, int]:
    """Giới hạn số câu hỏi AI mỗi người mỗi ngày (admin không giới hạn)."""
    if user_id in settings.admin_ids:
        return True, 0
    key = f"ai:{user_id}:{datetime.now(VN_TZ):%Y%m%d}"
    n = int(await storage.kv_get(key) or 0)
    if n >= settings.ai_daily_limit:
        return False, n
    await storage.kv_set(key, str(n + 1))
    return True, n + 1


def _fallback(question: str, ctx: str, reason: str) -> str:
    kind, explain = events.classify(question)
    head = f"🤖 <i>AI tạm thời không trả lời được ({escape(reason)}) — dưới đây là dữ liệu bot có sẵn:</i>\n\n"
    if kind != "other":
        return head + escape(explain)
    return head + escape(ctx[:1500])


async def answer(user_id: int, question: str) -> str:
    ok, n = await allowed(user_id)
    if not ok:
        return f"⏳ Bạn đã dùng hết {settings.ai_daily_limit} câu hỏi AI hôm nay. Mai hỏi tiếp nhé!"
    ctx = await market_context() + await _event_context(question)
    text, src = await ai.ask(question, ctx)
    if text is None:
        return _fallback(question, ctx, src)
    return f"🤖 {escape(text)}\n\n<i>Trả lời tự động từ dữ liệu bot · không phải lời khuyên đầu tư.</i>"


async def explain_event(user_id: int, e: dict) -> str:
    q = (f"Giải thích dễ hiểu tin '{e['title']}' lúc {e['time'].astimezone(VN_TZ):%H:%M %d/%m} (dự báo "
         f"{e.get('forecast') or 'chưa có'}, kỳ trước {e.get('previous') or 'chưa có'}): tin này là gì, số thực tế cao/thấp "
         "hơn dự báo thì thường ảnh hưởng crypto thế nào, người giao dịch nên lưu ý gì trước và sau giờ ra tin.")
    return await answer(user_id, q)


async def explain_signal(user_id: int, sig: dict) -> str:
    reasons = storage.loads(sig["reasons"]) if isinstance(sig.get("reasons"), str) else sig.get("reasons", [])
    facts = (f"Tín hiệu {sig['display']} {'LONG' if sig['side'] > 0 else 'SHORT'} ({sig.get('style')}), điểm "
             f"{sig['score']:.0f}/100, setup {sig['setup']}, vào {sig['entry']:.6g}, SL {sig['sl']:.6g}, TP1 {sig['tp1']:.6g}. "
             f"Lý do bot ghi nhận: {'; '.join(reasons)}.")
    q = ("Giải thích cho người mới vì sao bot đưa ra tín hiệu này (dựa vào các lý do đã ghi), rủi ro chính là gì và "
         f"cần theo dõi điều gì. Dữ liệu tín hiệu: {facts}")
    ok, _ = await allowed(user_id)
    if not ok:
        return f"⏳ Bạn đã dùng hết {settings.ai_daily_limit} câu hỏi AI hôm nay."
    text, src = await ai.ask(q, await market_context())
    if text is None:
        return (f"🧠 <b>{escape(sig['display'])}</b> — lý do bot chọn:\n" + "\n".join(f"• {escape(r)}" for r in reasons)
                + f"\n\n<i>(AI tạm thời không khả dụng: {escape(src)})</i>")
    return f"🧠 <b>Vì sao có tín hiệu {escape(sig['display'])}?</b>\n\n{escape(text)}"


async def ping() -> str:
    """Admin kiểm tra AI: nhà cung cấp nào đang trả lời."""
    text, src = await ai.ask("Trả lời đúng 1 từ: OK", "kiểm tra kết nối")
    return f"AI: {src} → {escape((text or '')[:50])}" if text else f"AI lỗi: {escape(src)}"
