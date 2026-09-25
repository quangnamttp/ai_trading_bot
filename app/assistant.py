"""Trợ lý hỏi đáp trong chat riêng: gom dữ liệu thật của bot làm ngữ cảnh cho AI; AI lỗi thì trả lời bằng dữ liệu có sẵn.

Theo chế độ người dùng đang chọn:
- Spot  -> chỉ hỏi về coin trong 💼 Danh mục (giá vốn, lời/lỗ, DCA bao nhiêu tiền ở mốc nào). Coin không có trong
           danh mục -> trả lời cố định, không gọi AI, không trừ lượt.
- Futures -> chỉ hỏi về tín hiệu bot đã gửi cho người đó và còn đang mở. Lệnh đã đóng -> trả kết quả, không phân tích.
- 🌍 Thị trường chung (nút riêng) -> tin tức, dữ liệu thị trường, mọi coin.
Câu hỏi ngoài phạm vi (thời tiết...) hoặc sai mục -> trả lời cố định, KHÔNG trừ lượt hỏi trong ngày.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime
from html import escape

from app import ai, events, portfolio as pf, storage
from app.config import VN_TZ, settings
from app.data import binance, macro, news
from app.strategy import levels

log = logging.getLogger(__name__)

FOOTER = ""
OUT_TEXT = ("🙅 Mình chỉ trả lời câu hỏi về crypto và giao dịch thôi nhé. "
            "Ví dụ: <i>Nên DCA SOL thế nào?</i>, <i>Khi nào lệnh ETH về bờ?</i>")
TO_MARKET = "🌍 Câu này về thị trường chung — hỏi ở <b>📰 Bot Tin tức</b> nhé."
TO_PERSONAL = "💼 Câu này về lệnh / danh mục của riêng bạn — hỏi ở <b>🤖 Bot Tín hiệu</b> (nút 🤖 Hỏi AI) nhé."
NOT_IN_PORTFOLIO = ("💼 Hiện tại danh mục của bạn không có đầu tư đồng coin <b>{coins}</b>.\n"
                    "Muốn hỏi về coin này: thêm vào 💼 Danh mục của tôi, hoặc hỏi ở 📰 Bot Tin tức.")
EMPTY_PORTFOLIO = "💼 Danh mục Spot của bạn đang trống. Bấm 💼 Danh mục của tôi → ➕ Thêm coin rồi hỏi lại nhé."
NO_SIGNAL = ("📊 Ở chế độ Futures, AI chỉ trả lời về tín hiệu bot đã gửi cho bạn và còn đang mở. "
             "{coins}Muốn xem một coin bất kỳ: dùng 🔍 Phân tích coin.")
PICK_SIGNAL = "📊 Bạn đang có nhiều lệnh mở — chọn lệnh muốn hỏi:"
MARKET_BUTTON = ("🌍 Hỏi ở mục Thị trường chung", "aimkt")  # đổi thành link Bot Tin tức khi có (market_button)


def market_button() -> tuple[str, str]:
    from app import reports
    return ("📰 Mở Bot Tin tức", f"https://t.me/{reports.NEWS_USERNAME}") if reports.NEWS_USERNAME else MARKET_BUTTON

# từ thường gặp trùng tên coin -> không coi là mã coin khi viết chữ thường
STOP = {"the", "and", "for", "how", "what", "gia", "mua", "ban", "nen", "khi", "sao", "can", "dca", "hot", "one",
        "near", "gas", "key", "dog", "sun", "ace", "bot", "ton", "tai", "cho", "voi", "con", "hay", "long", "short",
        "spot", "not", "big", "ens", "ren", "high", "low", "open", "close", "pump", "dump", "real", "true",
        "safe", "move", "ride", "bat", "cat", "fun", "win", "ask", "tao", "lai", "hoi", "anh", "chi", "em"}
IGNORE_UPPER = {"DCA", "SL", "TP", "TP1", "TP2", "OI", "RSI", "EMA", "ATR", "USD", "USDT", "VN", "AI", "FOMC", "CPI",
                "PPI", "NFP", "GDP", "PCE", "FED", "ETF", "LONG", "SHORT", "SPOT", "OK", "R", "POC", "VAH", "VAL",
                "VND", "VNĐ"}


async def find_symbols(text: str, limit: int = 3) -> list[str]:
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


# ---------------------------------------------------------------- ngữ cảnh
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


async def _coin_lines(symbols: list[str], *, spot_units: bool = False) -> list[str]:
    """Kế hoạch mốc giá bot tính cho từng coin. spot_units: đổi giá về 1 coin thật (chia hệ số 1000)."""
    lines = []
    for sym in symbols:
        try:
            p = await levels.coin_plan(sym)
            m = pf.mult_of(sym) if spot_units else 1
            fmt = (lambda x, m=m: f"{x / m:.6g}")
            lines.append(levels.plan_context(p, fmt))
            oi = await binance.oi_change_24h(sym)
            if oi:
                lines.append(f"- OI (Binance) thay đổi 24h: {oi[1]:+.1%}")
        except Exception as exc:  # noqa: BLE001
            log.debug("coin ctx %s: %s", sym, exc)
    return lines


def _now_line() -> str:
    return f"Thời gian hiện tại: {datetime.now(VN_TZ):%H:%M %d/%m/%Y} (giờ VN)"


async def market_context(question: str = "") -> str:
    lines = await _brief_market()
    evs = await events.week_events()
    if evs:
        lines.append("Lịch kinh tế Mỹ tuần này (giờ VN):")
        for e in evs[:15]:
            lines.append(f"- {e['time'].astimezone(VN_TZ):%d/%m %H:%M} {events.vi_title(e['title'])} (tác động "
                         f"{e.get('impact')}, dự báo {e.get('forecast') or '?'}, kỳ trước {e.get('previous') or '?'})")
    items = await news.headlines(24)
    if items:
        lines.append("Tin crypto 24h gần nhất:")
        lines += [f"- {h.title}" for h in items[:10]]
    if question:
        lines += await _coin_lines(await find_symbols(question))
    lines.append(_now_line())
    return "\n".join(lines)


def _state(s: dict) -> dict:
    st = storage.loads(s["state"]) if isinstance(s.get("state"), str) else s.get("state") or {}
    return st.get("trade", st)


def _reasons(s: dict) -> list[str]:
    return storage.loads(s["reasons"]) if isinstance(s.get("reasons"), str) else s.get("reasons", [])


def _signal_lines(s: dict) -> str:
    side = "LONG" if s["side"] > 0 else "SHORT"
    st = _state(s)
    extra = []
    if st.get("stop") is not None:
        extra.append(f"SL hiện tại {st['stop']:.6g}")
    if st.get("be_done"):
        extra.append("trailing stop đã kích hoạt")
    if st.get("hit"):
        extra.append("đã chốt 50% ở TP1")
    reasons = _reasons(s)
    return (f"Tín hiệu #{s['id']} {s['display']} {side} (swing {'ngắn' if s.get('style') == 'short' else 'dài'}, "
            f"trạng thái {s['status']}): vào {s['entry']:.6g}, SL ban đầu {s['sl']:.6g}, "
            f"{'TP1 (chốt 50%)' if st.get('partials') else 'mục tiêu tham khảo 2R (không chốt cố định, trailing chốt lời)'} "
            f"{s['tp1']:.6g}, điểm "
            f"{s['score']:.0f}/100" + (f", {', '.join(extra)}" if extra else "")
            + (f". Lý do bot: {'; '.join(reasons)}" if reasons else ""))


async def signal_context(s: dict) -> str:
    """Tiến độ 1 lệnh đang mở: giá hiện tại, đang lời/lỗ bao nhiêu R, cách giá vào / SL / TP1 bao nhiêu %."""
    lines = ["TÍN HIỆU NGƯỜI HỎI ĐANG HỎI: " + _signal_lines(s)]
    st = _state(s)
    try:
        px = await binance.last_price(s["symbol"])
        risk = abs(s["entry"] - s["sl"]) or 1e-12
        r_now = s["side"] * (px - s["entry"]) / risk
        stop = st.get("stop") or s["sl"]
        lines.append(f"- Giá hiện tại {px:.6g} → đang {'LỜI' if r_now >= 0 else 'LỖ'} {r_now:+.2f}R")
        if r_now < 0:
            lines.append(f"- Về bờ (hòa vốn) khi giá quay lại {s['entry']:.6g}, cách {abs(s['entry'] / px - 1):.2%}")
        tgt = "TP1" if st.get("partials") else "mục tiêu 2R"
        lines.append(f"- Cách SL {stop:.6g}: {abs(stop / px - 1):.2%} · cách {tgt} {s['tp1']:.6g}: {abs(s['tp1'] / px - 1):.2%}")
        if not st.get("be_done"):
            lines.append(f"- Trailing stop kích hoạt khi giá tới {s['entry'] + s['side'] * abs(s['entry'] - s['sl']):.6g} (+1R)")
        lines.append(f"- Lãi lớn nhất lệnh từng đạt: {st.get('max_r', 0):+.2f}R")
    except Exception as exc:  # noqa: BLE001
        log.debug("signal ctx: %s", exc)
    if s.get("created_at"):
        hours = (storage.now() - s["created_at"]).total_seconds() / 3600
        lines.append(f"- Lệnh đã mở {hours:.0f} giờ (swing {'ngắn giữ tối đa ~7 ngày' if s.get('style') == 'short' else 'dài giữ tối đa ~30 ngày'})")
    try:
        from app.strategy.scanner import live_derivs
        d = await live_derivs(s["symbol"], 24)
        if "oi_chg" in d:
            lines.append(f"- OI 24h hiện tại {d['oi_chg']:+.1%}")
        if "funding" in d:
            lines.append(f"- Funding hiện tại {d['funding']:.4%}/8h")
    except Exception as exc:  # noqa: BLE001
        log.debug("derivs ctx: %s", exc)
    return "\n".join(lines)


async def spot_context(user: dict, symbols: list[str]) -> str:
    cur = user.get("currency", "USDT")
    fx = await pf.rate(cur)
    if cur == "VND" and not fx:
        cur, fx = "USDT", 1.0
    lines = [f"Người hỏi dùng chế độ SPOT, đơn vị hiển thị {'VNĐ' if cur == 'VND' else 'USDT'}."]
    pos = {p["symbol"]: p for p in await storage.portfolio_of(user["chat_id"])}
    px = await pf.prices(list(pos))
    lines.append("Danh mục: " + ", ".join(pf.base_of(s) for s in pos))
    for sym in symbols:
        lines.append(pf.context_text(pos[sym], px.get(sym, {}).get("price"), cur, fx))
    lines += await _coin_lines(symbols, spot_units=True)
    lines += await _brief_market()
    lines.append(_now_line())
    return "\n".join(lines)


async def _event_context(question: str) -> str:
    """Nếu câu hỏi nhắc tới một loại tin (CPI, FOMC...) -> thêm giải thích + thống kê phản ứng BTC thật."""
    kind, explain = events.classify(question)
    if kind == "other":
        return ""
    st = await events.reaction_stats(kind)
    stat = re.sub(r"<[^>]+>", "", events.stats_text(st))
    return f"\nKiến thức của bot về loại tin này:\n{explain}\n{stat}"


# ---------------------------------------------------------------- nhớ hội thoại (để hỏi tiếp tự nhiên)
HIST_TURNS = 6
HIST_TTL = 2 * 3600
_HIST: dict[tuple[int, str], list[tuple[float, str, str]]] = {}


def history(user_id: int, quota: str) -> list[tuple[str, str]]:
    """Các lượt hỏi–đáp gần nhất (trong 2 giờ) của người này ở bot này."""
    now = time.time()
    turns = [t for t in _HIST.get((user_id, quota), []) if now - t[0] < HIST_TTL][-HIST_TURNS:]
    _HIST[(user_id, quota)] = turns
    return [(q, a) for _, q, a in turns]


def remember(user_id: int, quota: str, question: str, answer: str) -> None:
    _HIST.setdefault((user_id, quota), []).append((time.time(), question[:500], answer[:1500]))
    del _HIST[(user_id, quota)][:-HIST_TURNS]


def forget(user_id: int) -> None:
    for k in [k for k in _HIST if k[0] == user_id]:
        _HIST.pop(k, None)


async def coin_view(symbols: list[str], mode: str = "futures") -> str:
    """'PHÂN TÍCH CỦA BOT' cho coin được hỏi: kết luận có nên vào + kịch bản chờ (như nút 🔍), dạng chữ cho AI."""
    from app.bot.handlers import analysis_text
    from app.strategy.scanner import analyze_symbol
    out = []
    for sym in symbols[:2]:
        try:
            res = await analyze_symbol(sym)
            out.append(f"PHÂN TÍCH CỦA BOT cho {pf.base_of(sym)} (chế độ {mode.upper()}):\n"
                       + re.sub(r"<[^>]+>", "", analysis_text(res, mode)))
        except Exception as exc:  # noqa: BLE001
            log.debug("coin view %s: %s", sym, exc)
    return "\n\n".join(out)


# ---------------------------------------------------------------- lượt hỏi
def _quota_key(user_id: int, quota: str = "sig") -> str:
    return f"{'ai' if quota == 'sig' else 'ainews'}:{user_id}:{datetime.now(VN_TZ):%Y%m%d}"


def _limit(quota: str) -> int:
    return settings.ai_daily_limit if quota == "sig" else settings.ai_news_daily_limit


async def allowed(user_id: int, quota: str = "sig") -> tuple[bool, int]:
    """Còn lượt hỏi AI hôm nay không (admin không giới hạn). Mỗi bot có hạn mức riêng: 'sig' = Bot Tín hiệu,
    'news' = Bot Tin tức. Chỉ trừ lượt khi AI trả lời thật (xem `_consume`)."""
    if user_id in settings.admin_ids:
        return True, 0
    n = int(await storage.kv_get(_quota_key(user_id, quota)) or 0)
    return n < _limit(quota), n


async def _consume(user_id: int, quota: str = "sig") -> None:
    if user_id not in settings.admin_ids:
        await storage.kv_incr(_quota_key(user_id, quota))


def limit_text(quota: str = "sig") -> str:
    return f"⏳ Bạn đã dùng hết {_limit(quota)} câu hỏi AI hôm nay. Mai hỏi tiếp nhé!"


LIMIT_TEXT = limit_text()


def _fallback(question: str, ctx: str, reason: str) -> str:
    kind, explain = events.classify(question)
    head = f"🤖 <i>AI tạm thời không trả lời được ({escape(reason)}) — dưới đây là dữ liệu bot có sẵn:</i>\n\n"
    if kind != "other":
        return head + escape(explain)
    for mark in ("PHÂN TÍCH CỦA BOT", "VỊ THẾ SPOT", "TÍN HIỆU NGƯỜI HỎI", "KẾ HOẠCH DO BOT TÍNH"):
        i = ctx.find(mark)
        if i >= 0:
            return head + escape(ctx[i:].split("\nThời gian hiện tại")[0][:1800])
    return head + escape(ctx[:1500])


Reply = tuple[str, list[tuple[str, str]]]  # (nội dung HTML, các nút (chữ, callback_data))


async def _ask(user_id: int, question: str, ctx: str, scope: str, quota: str = "sig") -> Reply:
    ctx += await _event_context(question)
    text, src = await ai.ask(question, ctx, scope, history=history(user_id, quota))
    if text == ai.OUT_OF_SCOPE:
        return OUT_TEXT, []
    if text == ai.OTHER_PLACE:
        return (TO_PERSONAL, []) if scope == "market" else (TO_MARKET, [market_button()])
    if text is None:
        return _fallback(question, ctx, src), []
    await _consume(user_id, quota)
    remember(user_id, quota, question, text)
    return f"🤖 {escape(text)}{FOOTER}", []


def closed_text(s: dict) -> str:
    st = _state(s)
    r = s.get("result_r") or st.get("realized_r") or 0.0
    reason = {"SL": "chạm cắt lỗ", "BE": "về hòa vốn", "TRAIL": "trailing stop", "TP": "chốt lời",
              "TIMEOUT": "hết thời gian giữ lệnh"}.get(st.get("outcome", ""), "đã đóng")
    when = s["closed_at"].astimezone(VN_TZ).strftime("%H:%M %d/%m") if s.get("closed_at") else "?"
    return (f"📋 Lệnh <b>{escape(s['display'])} {'LONG' if s['side'] > 0 else 'SHORT'}</b> đã đóng lúc {when} "
            f"({reason}), kết quả <b>{r:+.2f}R</b>.\nLệnh đã đóng nên AI không phân tích thêm — xem tin "
            "📋 Tổng kết lệnh bot đã gửi ngay dưới tín hiệu.")


async def answer_personal(user: dict, question: str, signal: dict | None = None) -> Reply:
    """🤖 Hỏi AI ở Bot Tín hiệu. Dữ liệu đưa cho AI: Spot -> danh mục; Futures -> tín hiệu đang mở của người hỏi
    (hoặc tín hiệu đang được reply); kèm phân tích + kịch bản chờ của coin được nhắc tới và thị trường chung."""
    uid = user["chat_id"]
    if not (await allowed(uid))[0]:
        return LIMIT_TEXT, []
    if signal is not None and signal["status"] != "ACTIVE":
        return closed_text(signal), []
    asked = await find_symbols(question)
    syms = asked
    if not syms and history(uid, "sig"):  # hỏi tiếp ("còn giá vào thì sao?") -> coin của câu trước
        syms = await find_symbols(" ".join(q for q, _ in history(uid, "sig")[-2:]))
    brief = "\n".join(await _brief_market())
    if user.get("mode") == "spot":
        pos = [p["symbol"] for p in await storage.portfolio_of(uid)]
        chosen = [x for x in syms if x in pos] or (pos if len(pos) <= 3 and not syms else [])
        ctx = await spot_context(user, chosen) if pos else "Người hỏi dùng chế độ SPOT. Danh mục đang trống.\n" + brief
        others = [x for x in syms if x not in pos]
        if others:
            ctx += "\nCoin người hỏi nhắc tới nhưng CHƯA có trong danh mục: " + ", ".join(pf.base_of(x) for x in others)
        view = await coin_view(syms, "spot")
        return await _ask(uid, question, ctx + ("\n\n" + view if view else ""), "spot")

    if signal is not None:
        sigs = [signal]
    else:
        open_ = [x for x in await storage.user_signals(uid, days=45) if x["status"] == "ACTIVE"]
        sigs = [x for x in open_ if x["symbol"] in asked] or open_  # câu hỏi nêu coin -> chỉ lệnh coin đó
    parts = [await signal_context(x) for x in sigs[:4]] if sigs else ["Người hỏi hiện không có lệnh nào đang mở."]
    view = await coin_view([x for x in syms if not any(g["symbol"] == x for g in sigs)] if signal is None else [])
    if view:
        parts.append(view)
    parts.append(brief)
    return await _ask(uid, question, "\n\n".join(parts), "futures")


async def answer_market(user_id: int, question: str, quota: str = "news") -> Reply:
    """Hỏi AI thị trường chung (📰 Bot Tin tức): tin tức, lịch sự kiện, mọi coin, coin nào đang mạnh."""
    if not (await allowed(user_id, quota))[0]:
        return limit_text(quota), []
    syms = await find_symbols(question)
    if not syms and history(user_id, quota):  # hỏi tiếp -> coin của câu trước
        syms = await find_symbols(" ".join(q for q, _ in history(user_id, quota)[-2:]))
    view = await coin_view(syms)
    ctx = await market_context(question) + await _hot_context(question) + ("\n\n" + view if view else "")
    return await _ask(user_id, question, ctx, "market", quota)


async def _hot_context(question: str) -> str:
    """Hỏi 'coin nào nên chú ý / đang mạnh' -> thêm dữ liệu coin mạnh, OI, danh sách bot đang theo dõi."""
    if not re.search(r"coin nào|nên (vào|mua|chú ý)|đang mạnh|tiềm năng|đề xuất|gợi ý|top", question.lower()):
        return ""
    try:
        from app import reports
        return "\nDỮ LIỆU COIN ĐÁNG CHÚ Ý:\n" + re.sub(r"<[^>]+>", "", await reports.hot_coins_text())
    except Exception as exc:  # noqa: BLE001
        log.debug("hot ctx: %s", exc)
        return ""


async def explain_event(user_id: int, e: dict, quota: str = "news") -> str:
    q = (f"Giải thích dễ hiểu tin '{e['title']}' lúc {e['time'].astimezone(VN_TZ):%H:%M %d/%m} (dự báo "
         f"{e.get('forecast') or 'chưa có'}, kỳ trước {e.get('previous') or 'chưa có'}): tin này là gì, số thực tế cao/thấp "
         "hơn dự báo thì thường ảnh hưởng crypto thế nào, người giao dịch nên lưu ý gì trước và sau giờ ra tin.")
    return (await answer_market(user_id, q, quota))[0]


async def explain_signal(user_id: int, sig: dict, user: dict | None = None) -> str:
    reasons = _reasons(sig)
    if not (await allowed(user_id))[0]:
        return LIMIT_TEXT
    if sig["status"] != "ACTIVE":
        return closed_text(sig)
    q = ("Giải thích cho người mới vì sao bot đưa ra tín hiệu này (dựa vào các lý do đã ghi), rủi ro chính là gì và "
         "cần theo dõi điều gì cho tới khi lệnh đóng.")
    text, src = await ai.ask(q, await signal_context(sig), "futures")
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


# ---------------------------------------------------------------- dịch tiêu đề tin sang tiếng Việt
_vi_cache: dict[str, str] = {}


def _vi_key(title: str) -> str:
    return "vi:" + hashlib.sha1(title.encode()).hexdigest()[:32]


async def vi_titles(titles: list[str]) -> list[str]:
    """Dịch tiêu đề tin tiếng Anh sang tiếng Việt (1 lần gọi AI cho cả loạt, lưu lại để không dịch lặp).
    AI lỗi -> giữ tiêu đề gốc."""
    out = list(titles)
    todo = []
    for i, t in enumerate(titles):
        if t in _vi_cache:
            out[i] = _vi_cache[t]
            continue
        saved = await storage.kv_get(_vi_key(t))
        if saved:
            out[i] = _vi_cache[t] = saved
        else:
            todo.append(i)
    if not todo or not ai.enabled():
        return out
    prompt = "\n".join(f"{n}. {titles[i]}" for n, i in enumerate(todo, 1))
    text, _ = await ai.ask(f"Dịch {len(todo)} tiêu đề sau:\n{prompt}", "", "translate")
    if not text or text in (ai.OUT_OF_SCOPE, ai.OTHER_PLACE):
        return out
    got = dict((int(m.group(1)), m.group(2).strip()) for m in re.finditer(r"^\s*(\d+)[.)]\s*(.+)$", text, re.M))
    for n, i in enumerate(todo, 1):
        vi = got.get(n)
        if vi and len(vi) < 3 * len(titles[i]) + 40:
            out[i] = _vi_cache[titles[i]] = vi
            await storage.kv_set(_vi_key(titles[i]), vi)
    return out


async def ping() -> str:
    """Admin kiểm tra AI: nhà cung cấp nào đang trả lời."""
    text, src = await ai.ask("Trả lời đúng 1 từ: OK", "kiểm tra kết nối", "news")
    return f"AI: {src} → {escape((text or '')[:50])}" if text else f"AI lỗi: {escape(src)}"
