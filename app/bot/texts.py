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


STYLE_LABEL = {"short": "⚡ Swing ngắn", "long": "🌙 Swing dài"}
STYLE_HOLD = {"short": "giữ vài giờ → vài ngày", "long": "giữ vài ngày → vài tuần"}


def chase_limit(sig: dict) -> float:
    """Giá tối đa còn nên vào lệnh (quá mức này = đuổi giá, R:R xấu đi)."""
    return sig["entry"] + sig["side"] * 0.3 * abs(sig["entry"] - sig["sl"])


def signal_message(sig: dict, *, mode: str, risk_pct: float, stats: dict | None) -> str:
    """`sig`: bản ghi tín hiệu (giá theo hợp đồng futures). `mode`: spot | futures."""
    side, mult = sig["side"], sig["multiplier"] if mode == "spot" else 1
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
        + (" <i>(dự phòng — chất lượng thấp hơn hạng A)</i>" if tier == "B" else ""),
        "",
        f"💰 Vào ngay: <b>{p(entry)}</b> (giá thị trường)",
        f"⛔ Không vào nếu giá đã {'vượt' if side > 0 else 'xuống dưới'}: {p(chase_limit(sig))}",
        f"🛑 Cắt lỗ (SL): <b>{p(sl)}</b> (-{sl_pct:.1f}%)",
        f"🎯 Chốt 50% tại: <b>{p(sig['tp1'])}</b> (+{tp1_pct:.1f}%)",
    ]
    if sig.get("exit_mode") == "pct" and sig.get("callback"):
        act = entry + side * risk
        lines.append(f"🔁 Trailing Stop (cả lệnh): kích hoạt <b>{p(act)}</b>, callback <b>{sig['callback'] * 100:.1f}%</b>")
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
        lines.append("<i>📌 Đặt SL + TP1 + Trailing Stop trên sàn ngay khi vào lệnh là xong. Sàn không có Trailing Stop: "
                     "khi giá tới mức kích hoạt thì tự dời SL về giá vào.</i>")
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


def event_message(sig: dict, event: str, px: float, r: float, mode: str) -> str:
    mult = sig["multiplier"] if mode == "spot" else 1
    return EVENT_TEXT[event].format(d=escape(sig["display"]), px=price(px / mult), r=r)


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

<b>2 kiểu giao dịch</b> (chọn ở ⚙️)
• ⚡ <b>Swing ngắn</b>: tối đa 3 tín hiệu/ngày, chỉ từ 6h đến 22h, giữ vài giờ → vài ngày.
• 🌙 <b>Swing dài</b>: khoảng 1 tín hiệu/tuần, giữ vài ngày → vài tuần. Ban đêm vẫn gửi nhưng <b>không chuông</b>.
Hạng A = đạt chuẩn · Hạng B = chuẩn thấp hơn, chỉ gửi sau 15h nếu cả ngày chưa có tín hiệu.

<b>Cách vào lệnh</b> (đặt 1 lần trên sàn là xong)
1. Vào ngay theo giá thị trường. Không vào nếu giá đã vượt mức "Không vào".
2. Đặt <b>SL</b> ngay. Khối lượng theo gợi ý để mỗi lệnh chỉ mất tối đa % vốn đã chọn.
3. Đặt lệnh chốt <b>50% tại TP1</b>.
4. Đặt <b>Trailing Stop</b> cho cả lệnh: giá kích hoạt và callback % có trong tin nhắn.
   Sàn không có Trailing Stop: khi giá tới mức kích hoạt thì tự dời SL về giá vào.

<b>Lịch tự động</b>: 07:00 thị trường 24h · 15:05 danh sách theo dõi (nếu chưa có tín hiệu) · 22:00 tổng kết lời/lỗ.
Tạm dừng quanh tin vĩ mô Mỹ (CPI, FOMC, NFP) · cảnh báo nếu có tin xấu về coin bạn đang giữ lệnh.

<b>Trung thực về rủi ro</b>
Backtest 2 năm / 40 coin: khoảng 43% lệnh có lời, trung bình +0.2R/lệnh, chuỗi sụt giảm tệ nhất khoảng 16R
(= −8% vốn nếu rủi ro 0.5%/lệnh), khoảng 1/4 số tháng bị lỗ. Không tín hiệu nào chắc chắn thắng.

<b>Lệnh</b>: /start /menu /phantich SOL /thongke /mode
Giá tham chiếu Binance Futures — giá ở sàn khác có thể lệch nhẹ."""
