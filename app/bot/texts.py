"""Soạn nội dung tin nhắn tiếng Việt (HTML của Telegram)."""
from __future__ import annotations

import math
from datetime import datetime
from html import escape

from app.config import VN_TZ, settings


def price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}".rstrip("0").rstrip(".")
    digits = max(4, -int(math.floor(math.log10(p))) + 3)
    return f"{p:.{digits}f}".rstrip("0")


def vn_time(dt: datetime | None = None) -> str:
    return (dt or datetime.now(VN_TZ)).astimezone(VN_TZ).strftime("%H:%M %d/%m (GMT+7)")


def trend_label(side: int, trend_pts: float) -> str:
    strong = trend_pts >= 25
    if side > 0:
        return "🟢 Tăng mạnh" if strong else "🟢 Tăng"
    return "🔴 Giảm mạnh" if strong else "🔴 Giảm"


def sizing(entry: float, sl: float, risk_pct: float, max_lev: int | None = None) -> tuple[float, int]:
    """(khối lượng lệnh theo % vốn, đòn bẩy tối đa an toàn: giá thanh lý xa gấp đôi SL)."""
    sl_frac = abs(entry - sl) / entry
    size_pct = risk_pct / sl_frac
    safe_lev = max(1, min(max_lev or settings.max_leverage, int(0.5 / sl_frac)))
    return size_pct, safe_lev


STYLE_LABEL = {"short": "⚡ Swing ngắn", "long": "🌙 Swing dài", "ind1h": "🎯 Chỉ báo Swing 1H", "ind4h": "🎯 Chỉ báo Swing 4H"}
STYLE_HOLD = {"short": "giữ vài giờ → vài ngày", "long": "giữ vài ngày → vài tuần",
              "ind1h": "giữ tối đa 7 ngày", "ind4h": "giữ tối đa 4 tuần"}


def chase_limit(sig: dict) -> float:
    """Giá tối đa còn nên vào lệnh (quá mức này = đuổi giá, R:R xấu đi)."""
    return sig["entry"] + sig["side"] * 0.3 * abs(sig["entry"] - sig["sl"])


def disp_mult(sig: dict, mode: str, exchange: str | None = "Binance") -> int:
    """Hệ số chia giá khi hiển thị: Spot và sàn MEXC tính giá theo 1 coin (Binance Futures: 1000PEPE = 1000 coin)."""
    return (sig.get("multiplier") or 1) if (mode == "spot" or exchange == "MEXC") else 1


def signal_message(sig: dict, *, mode: str, risk_pct: float, stats: dict | None, exchange: str | None = "Binance",
                   ex_price: float | None = None) -> str:
    """`sig`: bản ghi tín hiệu (giá theo hợp đồng futures). `mode`: spot | futures. `exchange`: sàn người dùng giao
    dịch — MEXC thì thêm dòng giá MEXC lúc báo (`ex_price`, giá 1 coin) để biết lệch bao nhiêu."""
    side, mult = sig["side"], disp_mult(sig, mode, exchange)
    p = lambda v: price(v / mult)  # noqa: E731  giá spot = giá futures / hệ số (vd 1000PEPE)
    entry, sl = sig["entry"], sig["sl"]
    risk = abs(entry - sl)
    sl_pct = risk / entry * 100
    tp1_pct = abs(sig["tp1"] - entry) / entry * 100
    style = sig.get("style", "short")
    emoji, action = ("🟢", "MUA") if side > 0 else ("🔴", "BÁN")
    market = "Spot" if mode == "spot" else "Futures"
    tier = sig.get("tier", "A")
    max_lev = settings.long_max_leverage if style == "long" else settings.max_leverage
    size_pct, lev = sizing(entry, sl, risk_pct, max_lev)

    lines = [
        f"{emoji} <b>{escape(sig['display'])} | {action}</b> · {market} · {'LONG' if side > 0 else 'SHORT'}",
        f"{STYLE_LABEL.get(style, style)} ({STYLE_HOLD.get(style, '')}) · Hạng <b>{tier}</b>"
        + (" <i>(dự phòng — chất lượng thấp hơn hạng A)</i>" if tier == "B" and not style.startswith("ind") else ""),
        "",
        f"💰 Vào ngay: <b>{p(entry)}</b> (giá thị trường)"
        + (f"\n🏦 Giá MEXC lúc báo: <b>{price(ex_price)}</b> (lệch {ex_price / (entry / mult) - 1:+.2%})"
           if exchange == "MEXC" and ex_price else ""),
        f"⛔ Không vào nếu giá đã {'vượt' if side > 0 else 'xuống dưới'}: {p(chase_limit(sig))}",
        f"🛑 Cắt lỗ (SL): <b>{p(sl)}</b> (-{sl_pct:.1f}%)",
    ]
    sr = sig.get("sr") or {}
    ahead, behind = (sr.get("res"), sr.get("sup")) if side > 0 else (sr.get("sup"), sr.get("res"))
    if ahead or behind:  # vùng giá khung ngày: phía trước lệnh (cản) / phía sau lệnh (đỡ)
        parts = []
        if ahead:
            parts.append(f"{'Kháng cự' if side > 0 else 'Hỗ trợ'} gần: {p(ahead)} (cách {abs(ahead - entry) / max(risk, 1e-12):.1f}R)")
        if behind:
            parts.append(f"{'Hỗ trợ' if side > 0 else 'Kháng cự'} gần: {p(behind)}")
        lines.append("🧱 " + " · ".join(parts))
    partial = bool(sig.get("partials")) or sig.get("exit_mode") != "pct"  # lệnh trước v6 có chốt 50% ở TP1
    if partial:
        lines.append(f"🎯 Chốt 50% tại: <b>{p(sig['tp1'])}</b> (+{tp1_pct:.1f}%)")
    if sig.get("exit_mode") == "pct" and sig.get("callback"):
        act = entry + side * risk
        lines.append(f"🔁 Trailing Stop (cả lệnh): kích hoạt <b>{p(act)}</b>, callback <b>{sig['callback'] * 100:.1f}%</b>")
        if not partial:
            lines.append(f"🎯 Mục tiêu tham khảo: {p(sig['tp1'])} (+{tp1_pct:.1f}%) — không đặt chốt cố định, trailing tự chốt lời")
    else:
        lines.append(f"🚀 Mục tiêu tham khảo: {p(sig['tp2'])} (phần còn lại chạy trailing)")
    if mode == "futures":
        lines.append(f"⚖️ Khối lượng {size_pct:.0f}% vốn · đòn bẩy tối đa x{lev} · rủi ro {risk_pct:g}% vốn")
    else:
        lines.append(f"⚖️ Khối lượng gợi ý: {min(size_pct, 100):.0f}% vốn (mất {risk_pct:g}% vốn nếu chạm SL)")
    lines.append("")
    lines.append(f"🤖 Điểm: <b>{sig['score']:.0f}/100</b> · Xu hướng: {trend_label(side, sig.get('trend', 0))}")
    if stats:
        lines.append(f"📊 Backtest mức điểm này: {stats['win_rate']:.0%} lệnh có lời · TB {stats['avg_r']:+.2f}R ({stats['n']} lệnh)")
    lines.append(f"🧭 {escape(sig['setup_text'])}")
    for r in sig.get("reasons", [])[:4]:
        lines.append(f"   • {escape(r)}")
    lines.append(f"🕒 {vn_time(sig.get('created_at'))}")
    if sig.get("exit_mode") == "pct":
        lines.append("<i>📌 Đặt SL + " + ("TP1 + " if partial else "") + "Trailing Stop trên sàn ngay khi vào lệnh là xong. "
                     "Sàn không có Trailing Stop: khi giá tới mức kích hoạt thì dời SL về giá vào rồi dời theo giá.</i>")
    else:
        lines.append("<i>📌 Giá lãi +1R → dời SL về giá vào. Luôn đặt SL — tín hiệu không đảm bảo thắng.</i>")
    return "\n".join(lines)


EVENT_TEXT = {
    "BE": "🔒 <b>{d}</b>: giá đã đi +1R — <b>dời SL về giá vào {px}</b> (lệnh không còn rủi ro).",
    "ARMED": "🔒 <b>{d}</b>: giá tới +1R ({px}) — Trailing Stop trên sàn đã kích hoạt. "
             "Nếu bạn không đặt Trailing Stop: dời SL về giá vào lệnh.",
    "TP1": "✅ <b>{d}</b>: chạm <b>TP1 {px}</b> — chốt 50% vị thế, phần còn lại để trailing chạy.",
    "TRAIL_MOVE": "📈 <b>{d}</b>: dời SL lên <b>{px}</b> để khóa lãi.",
    "SL": "❌ <b>{d}</b>: chạm cắt lỗ {px}. Kết quả: <b>{r:+.2f}R</b>.",
    "STOPPED": "🏁 <b>{d}</b>: đóng lệnh tại {px}. Kết quả cả lệnh: <b>{r:+.2f}R</b>.",
    "TIMEOUT": "⌛ <b>{d}</b>: hết thời gian giữ lệnh, đóng tại {px}. Kết quả: <b>{r:+.2f}R</b>.",
}


def event_message(sig: dict, event: str, px: float, r: float, mode: str, exchange: str | None = "Binance") -> str:
    mult = disp_mult(sig, mode, exchange)
    return EVENT_TEXT[event].format(d=escape(sig["display"]), px=price(px / mult), r=r)


OUTCOME_TEXT = {"SL": "chạm cắt lỗ", "BE": "về hòa vốn", "TRAIL": "trailing stop", "TP": "chốt lời",
                "TIMEOUT": "hết thời gian giữ lệnh"}


def close_summary(sig: dict, trade, *, risk_pct: float, hours: float, btc_chg: float | None) -> str:
    """📋 Tổng kết lệnh khi đóng: kết quả, lý do đóng, lãi lớn nhất từng đạt, BTC trong lúc giữ lệnh, bài học ngắn."""
    r = trade.realized_r
    side = "LONG" if sig["side"] > 0 else "SHORT"
    lines = [f"📋 <b>Tổng kết lệnh {escape(sig['display'])} {side}</b>",
             f"Kết quả: <b>{r:+.2f}R</b> = <b>{r * risk_pct:+.2f}% vốn</b> (rủi ro {risk_pct:g}%/lệnh)",
             f"Đóng vì: {OUTCOME_TEXT.get(trade.outcome, trade.outcome or 'đã đóng')} · giữ {hours:.0f} giờ",
             f"Lãi lớn nhất từng đạt: {trade.max_r:+.1f}R"]
    if btc_chg is not None:
        lines.append(f"BTC trong lúc giữ lệnh: {btc_chg:+.1%}")
    lesson = []
    against = btc_chg is not None and btc_chg * sig["side"] < -0.02
    if r > 0.05:
        lesson.append("Lệnh đi đúng hướng; để trailing stop chốt lời là đúng quy tắc.")
    elif trade.outcome == "TIMEOUT":
        lesson.append("Giá đi ngang quá lâu — bot đóng để giải phóng vốn cho cơ hội khác.")
    elif trade.max_r >= 1:
        lesson.append(f"Lệnh từng lãi +{trade.max_r:.1f}R rồi quay đầu — trailing / dời SL đã giữ lại phần có thể.")
    elif trade.max_r < 0.3:
        lesson.append("Giá đi ngược gần như ngay sau khi vào — setup không được thị trường xác nhận; "
                      "SL giới hạn thiệt hại đúng kế hoạch.")
    else:
        lesson.append("Giá có nhích đúng hướng nhưng không đủ lực; SL cắt lỗ đúng kế hoạch.")
    if against and r <= 0:
        lesson.append(f"BTC chạy ngược {btc_chg:+.1%} kéo cả thị trường — altcoin khó thắng khi BTC đi mạnh ngược chiều.")
    lines.append("💡 " + " ".join(lesson))
    lines.append("<i>Lệnh lỗ là một phần của hệ thống — đánh giá sau nhiều lệnh, không theo từng lệnh.</i>")
    return "\n".join(lines)


def stats_message(rows: list[dict], title: str) -> str:
    if not rows:
        return f"📈 <b>{title}</b>\nChưa có lệnh nào đóng."
    r = [x["result_r"] or 0 for x in rows]
    wins = sum(1 for v in r if v > 0)
    return (f"📈 <b>{title}</b>\n"
            f"Số lệnh đã đóng: {len(r)}\n"
            f"Lệnh có lời: {wins} ({wins / len(r):.0%})\n"
            f"Tổng: <b>{sum(r):+.2f}R</b> · TB {sum(r) / len(r):+.2f}R/lệnh\n"
            f"Tốt nhất {max(r):+.2f}R · Tệ nhất {min(r):+.2f}R\n"
            f"<i>1R = số tiền bạn chấp nhận mất mỗi lệnh (vd 0.5% vốn).</i>")


HELP = """ℹ️ <b>Hướng dẫn sử dụng</b>

<b>Bot làm gì?</b> Quét top 20 coin Binance Futures, chấm điểm xu hướng (1D/4H), động lượng, setup (hồi/retest),
dòng tiền (taker, CVD), phái sinh (funding, OI, tỉ lệ long/short), thị trường chung (BTC, Fear &amp; Greed, tin tức).
Chỉ vào lệnh khi có xác nhận: OI biến động mạnh, hoặc đám đông nghiêng hẳn về phía ngược lại, hoặc setup Retest.

<b>2 kiểu giao dịch</b> (chọn ở ⚙️ Cài đặt, Spot chỉ có Swing ngắn)
• ⚡ <b>Swing ngắn</b>: tối đa 3 tín hiệu/ngày, chỉ từ 6h đến 22h, giữ vài giờ → vài ngày.
• 🌙 <b>Swing dài</b>: khoảng 1 tín hiệu/tuần, giữ vài ngày → vài tuần. Ban đêm vẫn gửi nhưng <b>không chuông</b>.
Hạng A = đạt chuẩn · Hạng B = chuẩn thấp hơn, chỉ gửi sau 15h nếu cả ngày chưa có tín hiệu.

<b>Cách vào lệnh</b> (đặt 1 lần trên sàn là xong)
1. Vào ngay theo giá thị trường. Không vào nếu giá đã vượt mức "Không vào".
2. Đặt <b>SL</b> ngay. Khối lượng theo gợi ý để mỗi lệnh chỉ mất tối đa % vốn đã chọn.
3. Đặt <b>Trailing Stop</b> cho cả lệnh: giá kích hoạt (+1R) và callback % có trong tin nhắn. Không đặt chốt cố định —
   trailing tự chốt lời (backtest 9 năm: lời nhiều hơn và sụt giảm ít hơn chốt 50% ở 2R).
   Sàn không có Trailing Stop: khi giá tới mức kích hoạt thì dời SL về giá vào rồi dời theo giá.

<b>⚙️ Cài đặt</b>: Spot (chỉ MUA) / Futures (LONG &amp; SHORT), % rủi ro, kiểu swing, bật/tắt tín hiệu, đơn vị USDT/VNĐ.
Menu tự đổi theo chế độ đang chọn.

<b>💼 Danh mục của tôi</b> (Spot, tối đa 20 coin)
• ➕ Mua / ➖ Bán: gõ số tiền đã mua (vd <code>100</code> hoặc <code>2tr</code>) → bot tự tính số coin và giá vốn trung bình.
• 🎯 Đặt vốn DCA: gõ tổng tiền dự kiến mua thêm → bot chia vào các vùng hỗ trợ (30% / 30% / 40%) và <b>nhắc khi giá
chạm vùng</b>. Mua trên sàn xong bấm ✅ Đã mua là danh mục tự cập nhật.
• Bot cảnh báo coin trong danh mục khi xu hướng đổi chiều, thủng vùng giá, OI/funding bất thường, có tin xấu.
• 22:00 báo giá trị danh mục, lời/lỗ.

<b>🪙 Coin theo dõi</b> (Futures, tối đa 20): thêm coin muốn nhận tín hiệu ngoài Top 20.

<b>🔍 Phân tích coin</b>: gõ tên coin → bot KẾT LUẬN có thể vào LONG/SHORT (kèm giá vào, SL, trailing) hay chưa nên vào; chưa nên thì nói rõ còn thiếu điều kiện gì, mốc giá cần để ý, và nút ➕ Theo dõi để bot tự báo khi đủ điều kiện.

<b>🎯 Tín hiệu chỉ báo Swing</b> (bật trong 🪙 / 💼): nến 1H hoặc 4H đóng mà coin bạn chọn đủ điều kiện chỉ báo
Swing Entry Pro → bot gửi giống nhãn MUA/BÁN trên TradingView và theo dõi lệnh. Nên chọn khung 4H (backtest 9 năm tốt hơn 1H rõ rệt). Chọn không chuông, tối đa 1–5 tin/ngày.

🧱 Mỗi tín hiệu có dòng kháng cự / hỗ trợ gần nhất để biết giá sắp gặp vùng nào — chỉ để tham khảo, không cần bỏ lệnh vì vùng cản gần.

<b>Lịch tự động</b>: 15:05 danh sách theo dõi (nếu chưa có tín hiệu) · 22:00 tổng kết cá nhân · chủ nhật 22:05
tổng kết lệnh tuần · lệnh đóng → 📋 Tổng kết lệnh. Tin tức, thị trường, lịch sự kiện: 📰 Bot Tin tức.

<b>🤖 Hỏi AI</b> (50 câu/ngày · câu ngoài phạm vi không tính lượt)
• Hỏi như nói chuyện, AI nhớ câu trước. Hỏi được về lệnh của bạn, bất kỳ coin nào (dùng phân tích của bot), kiến thức giao dịch; có thể reply vào tin tín hiệu.

<b>Trung thực về rủi ro</b>
Backtest 2 năm gần nhất / 40 coin: swing ngắn 45% lệnh có lời, TB +0.2R/lệnh, sụt giảm tệ nhất ~15R (= −7.5% vốn
nếu rủi ro 0.5%/lệnh), khoảng 1/4 số tháng lỗ; swing dài TB +0.43R/lệnh. Kiểm tra thêm 9 năm / 50 coin: không năm nào
lỗ với khung 1H. Không tín hiệu nào chắc chắn thắng.

Mọi chức năng nằm ở bàn phím nút bên dưới ô nhập tin (bấm ⌘ nếu bị ẩn, hoặc gõ /start).
Giá tham chiếu Binance Futures — giá ở sàn khác có thể lệch nhẹ."""
