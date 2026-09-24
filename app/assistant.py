"""Trợ lý hỏi đáp: gom dữ liệu thật của bot làm ngữ cảnh cho AI; AI lỗi thì trả lời bằng dữ liệu có sẵn.

2 trợ lý:
- "trade" (chat riêng với bot): tín hiệu, lệnh đang mở, coin của tôi, kế hoạch DCA / vùng vào lệnh 1 coin (mốc giá do
  bot tính), reply vào tin tín hiệu để hỏi về đúng lệnh đó.
- "market" (topic 💬 Hỏi đáp của nhóm): thị trường chung, mọi coin, tin tức, lịch kinh tế.
Câu hỏi ngoài phạm vi (thời tiết...) hoặc sai chỗ -> trả lời cố định, KHÔNG trừ lượt hỏi trong ngày.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from html import escape

from app import ai, events, storage
from app.config import VN_TZ, settings
from app.data import binance, macro, news
from app.strategy import levels

log = logging.getLogger(__name__)

FOOTER = "\n\n<i>Trả lời tự động từ dữ liệu bot · không phải lời khuyên đầu tư.</i>"
OUT_TEXT = ("🙅 Mình chỉ trả lời câu hỏi về crypto và giao dịch thôi nhé. "
            "Ví dụ: <i>Lập kế hoạch DCA cho SOL</i>, <i>Tuần này có tin gì ảnh hưởng BTC?</i>")
TO_GROUP = ("💬 Câu này về thị trường chung — hỏi trong topic <b>💬 Hỏi đáp AI</b> của nhóm nhé. "
            "Ở đây mình trả lời về tín hiệu, lệnh của bạn, kế hoạch DCA / vùng vào lệnh cho 1 coin.")
TO_BOT = ("🔒 Câu này về lệnh / tài khoản của riêng bạn — hỏi trong chat riêng với bot nhé "
          "(bấm 🤖 Hỏi AI, hoặc reply vào tin tín hiệu).")
# từ thường gặp trùng tên coin -> không coi là mã coin khi viết chữ thường
STOP = {"the", "and", "for", "how", "what", "gia", "mua", "ban", "nen", "khi", "sao", "can", "dca", "hot", "one",
        "near", "gas", "key", "dog", "sun", "ace", "bot", "ton", "tai", "cho", "voi", "con", "hay", "long", "short",
        "spot", "not", "big", "ens", "ren", "high", "low", "open", "close", "pump", "dump", "real", "true",
        "safe", "move", "ride", "bat", "cat", "fun", "win", "ask", "tao", "lai", "ban", "hoi", "anh", "chi", "em"}
IGNORE_UPPER = {"DCA", "SL", "TP", "TP1", "TP2", "OI", "RSI", "EMA", "ATR", "USD", "USDT", "VN", "AI", "FOMC", "CPI",
                "PPI", "NFP", "GDP", "PCE", "FED", "ETF", "LONG", "SHORT", "SPOT", "OK", "R", "POC", "VAH", "VAL"}


async def find_symbols(text: str, limit: int = 2) -> list[str]:
    """Mã coin (Binance Futures) được nhắc tới trong câu hỏi, vd 'dca sol' -> SOLUSDT, 'PEPE' -> 1000PEPEUSDT."""
    try:
        perps = await binance.perpetual_symbols()
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for tok in re.findall(r"(?<![A-Za-z0-9À-ỹ])[A-Za-z0-9]{2,12}(?![A-Za-z0-9À-ỹ])", text):
        up = tok.upper()
        if up in IGNORE_UPPER:
            continue
        if not tok.isupper() and (len(tok) < 3 or tok.lower() in STOP):
            continue
        base = re.sub(r"(USDT|USDC|PERP|\.P)$", "", up) or up
        for sym in (f"{base}USDT", f"1000{base}USDT"):
            if sym in perps and sym not in out:
                out.append(sym)
                break
        if len(out) >= limit:
            break
    return out


async def _brief_market() -> list[str]:
    lines = []
    try:
        tick = await binance.tickers_24h()
        for sym in ("BTCUSDT", "ETHUSDT"):
            t = tick.get(sym)
            if t:
                lines.append(f"{sym[:3]}: {float(t['lastPrice']):.2f} USD ({float(t['priceChangePercent']):+.2f}% 24h)")
        fg = await macro.fear_greed_now()
        if fg:
            lines.append(f"Chỉ số Fear & Greed hôm nay: {fg[0]}/100 ({fg[1]})")
        f = await binance.all_funding()
        if "BTCUSDT" in f:
            lines.append(f"Funding BTC: {f['BTCUSDT']:.4%}/8h")
    except Exception as exc:  # noqa: BLE001
        log.debug("market ctx: %s", exc)
    return lines


async def _coin_lines(symbols: list[str]) -> list[str]:
    lines = []
    for sym in symbols:
        try:
            lines.append(levels.plan_context(await levels.coin_plan(sym)))
            oi = await binance.oi_change_24h(sym)
            if oi:
                lines.append(f"- OI (Binance) thay đổi 24h: {oi[1]:+.1%}")
        except Exception as exc:  # noqa: BLE001
            log.debug("coin ctx %s: %s", sym, exc)
    return lines


async def market_context(question: str = "") -> str:
    lines = await _brief_market()
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
    if question:
        lines += await _coin_lines(await find_symbols(question))
    lines.append(f"Thời gian hiện tại: {datetime.now(VN_TZ):%H:%M %d/%m/%Y} (giờ VN)")
    return "\n".join(lines)


def _signal_lines(s: dict) -> str:
    side = "LONG" if s["side"] > 0 else "SHORT"
    reasons = storage.loads(s["reasons"]) if isinstance(s.get("reasons"), str) else s.get("reasons", [])
    st = storage.loads(s["state"]) if isinstance(s.get("state"), str) else s.get("state") or {}
    st = st.get("trade", st)
    extra = []
    if st.get("stop") is not None:
        extra.append(f"SL hiện tại {st['stop']:.6g}")
    if st.get("be_done"):
        extra.append("trailing stop đã kích hoạt")
    if st.get("hit"):
        extra.append("đã chốt 50% ở TP1")
    return (f"Tín hiệu #{s['id']} {s['display']} {side} (swing {'ngắn' if s.get('style') == 'short' else 'dài'}, "
            f"trạng thái {s['status']}): vào {s['entry']:.6g}, SL {s['sl']:.6g}, TP1 {s['tp1']:.6g}, điểm {s['score']:.0f}/100"
            + (f", {', '.join(extra)}" if extra else "") + (f". Lý do bot: {'; '.join(reasons)}" if reasons else ""))


async def trade_context(user: dict, question: str, signal: dict | None = None) -> str:
    lines = [f"Người hỏi: chế độ {'SPOT (chỉ mua, không short, không đòn bẩy)' if user.get('mode') == 'spot' else 'FUTURES'}, "
             f"rủi ro {user.get('risk_pct', 0.5):g}% vốn mỗi lệnh."]
    coins = await storage.user_coins_of(user["chat_id"])
    if coins:
        lines.append("Coin người hỏi theo dõi: " + ", ".join(
            binance.split_symbol(c["symbol"])[0] + (" (đang giữ)" if c["holding"] else "") for c in coins))
    if signal:
        lines.append("TÍN HIỆU NGƯỜI HỎI ĐANG REPLY: " + _signal_lines(signal))
        try:
            lines.append(f"Giá hiện tại {signal['display']}: {await binance.last_price(signal['symbol']):.6g}")
        except Exception:  # noqa: BLE001
            pass
    mine = []
    for s in await storage.open_signals():
        if any(m["chat_id"] == user["chat_id"] for m in await storage.messages_for(s["id"])):
            mine.append(s)
    if mine:
        lines.append("Lệnh đang mở người hỏi đã nhận:")
        lines += ["- " + _signal_lines(s) for s in mine[:6]]
    else:
        lines.append("Người hỏi chưa có lệnh nào đang mở từ bot.")
    syms = await find_symbols(question)
    if not syms and signal:
        syms = [signal["symbol"]]
    lines += await _coin_lines(syms)
    lines += await _brief_market()
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


def _quota_key(user_id: int) -> str:
    return f"ai:{user_id}:{datetime.now(VN_TZ):%Y%m%d}"


async def allowed(user_id: int) -> tuple[bool, int]:
    """Còn lượt hỏi AI hôm nay không (admin không giới hạn). Chỉ trừ lượt khi AI trả lời thật (xem `_consume`)."""
    if user_id in settings.admin_ids:
        return True, 0
    n = int(await storage.kv_get(_quota_key(user_id)) or 0)
    return n < settings.ai_daily_limit, n


async def _consume(user_id: int) -> None:
    if user_id not in settings.admin_ids:
        await storage.kv_incr(_quota_key(user_id))


def _fallback(question: str, ctx: str, reason: str) -> str:
    kind, explain = events.classify(question)
    head = f"🤖 <i>AI tạm thời không trả lời được ({escape(reason)}) — dưới đây là dữ liệu bot có sẵn:</i>\n\n"
    if kind != "other":
        return head + escape(explain)
    plan = ctx.find("KẾ HOẠCH DO BOT TÍNH")
    if plan >= 0:
        return head + escape(ctx[plan:].split("\nThời gian hiện tại")[0][:1800])
    return head + escape(ctx[:1500])


async def answer(user_id: int, question: str, *, scope: str = "market", user: dict | None = None,
                 signal: dict | None = None) -> str:
    ok, _ = await allowed(user_id)
    if not ok:
        return f"⏳ Bạn đã dùng hết {settings.ai_daily_limit} câu hỏi AI hôm nay. Mai hỏi tiếp nhé!"
    if scope == "trade" and user:
        ctx = await trade_context(user, question, signal)
    else:
        ctx = await market_context(question)
    ctx += await _event_context(question)
    text, src = await ai.ask(question, ctx, scope)
    if text == ai.OUT_OF_SCOPE:
        return OUT_TEXT
    if text == ai.OTHER_PLACE:
        return TO_GROUP if scope == "trade" else TO_BOT
    if text is None:
        return _fallback(question, ctx, src)
    await _consume(user_id)
    return f"🤖 {escape(text)}{FOOTER}"


async def explain_event(user_id: int, e: dict) -> str:
    q = (f"Giải thích dễ hiểu tin '{e['title']}' lúc {e['time'].astimezone(VN_TZ):%H:%M %d/%m} (dự báo "
         f"{e.get('forecast') or 'chưa có'}, kỳ trước {e.get('previous') or 'chưa có'}): tin này là gì, số thực tế cao/thấp "
         "hơn dự báo thì thường ảnh hưởng crypto thế nào, người giao dịch nên lưu ý gì trước và sau giờ ra tin.")
    return await answer(user_id, q)


async def explain_signal(user_id: int, sig: dict, user: dict | None = None) -> str:
    reasons = storage.loads(sig["reasons"]) if isinstance(sig.get("reasons"), str) else sig.get("reasons", [])
    ok, _ = await allowed(user_id)
    if not ok:
        return f"⏳ Bạn đã dùng hết {settings.ai_daily_limit} câu hỏi AI hôm nay."
    q = ("Giải thích cho người mới vì sao bot đưa ra tín hiệu này (dựa vào các lý do đã ghi), rủi ro chính là gì và "
         "cần theo dõi điều gì cho tới khi lệnh đóng.")
    ctx = await trade_context(user or {"chat_id": user_id}, q, sig)
    text, src = await ai.ask(q, ctx, "trade")
    if text is None or text in (ai.OUT_OF_SCOPE, ai.OTHER_PLACE):
        return (f"🧠 <b>{escape(sig['display'])}</b> — lý do bot chọn:\n" + "\n".join(f"• {escape(r)}" for r in reasons)
                + f"\n\n<i>(AI tạm thời không khả dụng: {escape(src)})</i>")
    await _consume(user_id)
    return f"🧠 <b>Vì sao có tín hiệu {escape(sig['display'])}?</b>\n\n{escape(text)}"


async def news_summary(prompt: str, context: str) -> str | None:
    """Tóm tắt tin ngắn cho topic 📰 (không tính lượt của ai). None nếu AI không khả dụng."""
    if not ai.enabled():
        return None
    text, _ = await ai.ask(prompt, context, "news")
    return text if text and text not in (ai.OUT_OF_SCOPE, ai.OTHER_PLACE) else None


async def ping() -> str:
    """Admin kiểm tra AI: nhà cung cấp nào đang trả lời."""
    text, src = await ai.ask("Trả lời đúng 1 từ: OK", "kiểm tra kết nối", "news")
    return f"AI: {src} → {escape((text or '')[:50])}" if text else f"AI lỗi: {escape(src)}"
