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


def sizing(entry: float, sl: float, risk_pct: float) -> tuple[float, int]:
    """(khối lượng lệnh theo % vốn, đòn bẩy tối đa an toàn: giá thanh lý xa gấp đôi SL)."""
    sl_frac = abs(entry - sl) / entry
    size_pct = risk_pct / sl_frac
    safe_lev = max(1, min(settings.max_leverage, int(0.5 / sl_frac)))
    return size_pct, safe_lev


def signal_message(sig: dict, *, mode: str, risk_pct: float, stats: dict | None) -> str:
    """`sig`: bản ghi tín hiệu (giá theo hợp đồng futures). `mode`: spot | futures."""
    side, mult = sig["side"], sig["multiplier"] if mode == "spot" else 1
    p = lambda v: price(v / mult)  # noqa: E731  giá spot = giá futures / hệ số (vd 1000PEPE)
    entry, sl = sig["entry"], sig["sl"]
    sl_pct = abs(entry - sl) / entry * 100
    tp1_pct = abs(sig["tp1"] - entry) / entry * 100
    emoji, action = ("🟢", "MUA") if side > 0 else ("🔴", "BÁN")
    market = "Spot" if mode == "spot" else "Futures"
    lo, hi = (sig["zone_lo"], sig["zone_hi"]) if side > 0 else (sig["zone_hi"], sig["zone_lo"])
    size_pct, lev = sizing(entry, sl, risk_pct)

    lines = [
        f"{emoji} <b>{escape(sig['display'])} | {action}</b> · {market} · {'LONG' if side > 0 else 'SHORT'}",
        f"💰 Vùng vào lệnh: <b>{p(hi)} → {p(lo)}</b>",
        f"🎯 Giá chốt lời: <b>{p(sig['tp1'])}</b> (+{tp1_pct:.1f}%, chốt 50%)",
        f"🚀 Mục tiêu mở rộng: {p(sig['tp2'])} (phần còn lại chạy trailing)",
        f"🛑 Giá cắt lỗ: <b>{p(sl)}</b> (-{sl_pct:.1f}%)",
    ]
    if mode == "futures":
        margin = size_pct / lev
        lines.append(f"⚖️ Khối lượng: {size_pct:.0f}% vốn · đòn bẩy tối đa x{lev} (ký quỹ ~{margin:.0f}% vốn) · rủi ro {risk_pct:g}%")
    else:
        lines.append(f"⚖️ Khối lượng gợi ý: {min(size_pct, 100):.0f}% vốn (rủi ro {risk_pct:g}% vốn nếu chạm SL)")
    lines.append(f"🤖 Điểm tín hiệu: <b>{sig['score']:.0f}/100</b>")
    if stats:
        lines.append(f"📊 Backtest cùng mức điểm: {stats['win_rate']:.0%} lệnh có lời · TB {stats['avg_r']:+.2f}R/lệnh ({stats['n']} lệnh)")
    lines.append(f"📈 Xu hướng: {trend_label(side, sig.get('trend', 0))}")
    lines.append(f"🧭 Setup: {escape(sig['setup_text'])}")
    for r in sig.get("reasons", [])[:4]:
        lines.append(f"   • {escape(r)}")
    lines.append(f"🕒 Thời gian: {vn_time(sig.get('created_at'))}")
    lines.append("<i>📌 Giá lãi +1R → dời SL về entry. Sau TP1 bot sẽ báo dời SL theo xu hướng. "
                 "Luôn đặt SL — tín hiệu không đảm bảo thắng.</i>")
    return "\n".join(lines)


EVENT_TEXT = {
    "BE": "🔒 <b>{d}</b>: giá đã đi +1R — <b>dời SL về entry {px}</b> (lệnh không còn rủi ro).",
    "TP1": "✅ <b>{d}</b>: chạm <b>TP1 {px}</b> — chốt 50% vị thế, phần còn lại để chạy.",
    "TRAIL_MOVE": "📈 <b>{d}</b>: dời SL lên <b>{px}</b> để khóa lãi.",
    "SL": "❌ <b>{d}</b>: chạm cắt lỗ {px}. Kết quả: <b>{r:+.2f}R</b>.",
    "STOPPED": "🏁 <b>{d}</b>: đóng phần còn lại tại {px}. Kết quả cả lệnh: <b>{r:+.2f}R</b>.",
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

<b>Bot làm gì?</b> Mỗi giờ quét top coin Binance Futures, chấm điểm 6 nhóm dữ liệu:
xu hướng 1D/4H, động lượng, setup, dòng tiền taker (CVD), phái sinh (funding, OI, tỉ lệ long/short),
thị trường chung (BTC, Fear &amp; Greed, thanh khoản stablecoin, tin tức). Chỉ gửi 1–5 tín hiệu/ngày tốt nhất.
Tạm dừng quanh tin vĩ mô Mỹ (CPI, FOMC, NFP...) và khi có tin xấu nghiêm trọng về coin.

<b>Chế độ</b>
• <b>Spot</b>: chỉ nhận lệnh MUA, giá theo sàn spot.
• <b>Futures</b>: nhận cả LONG/SHORT, kèm khối lượng và đòn bẩy an toàn.

<b>Cách vào lệnh</b>
1. Vào lệnh trong vùng entry (không đuổi nếu giá đã chạy xa).
2. Đặt SL ngay. Khối lượng theo gợi ý để mỗi lệnh chỉ mất tối đa % vốn đã chọn.
3. Lãi +1R → dời SL về entry. Tới TP1 → chốt 50%.
4. Phần còn lại: làm theo tin nhắn dời SL của bot.

<b>Trung thực về rủi ro</b>
Backtest 1 năm: chỉ khoảng 1/3 số lệnh có lời, lợi nhuận đến từ số ít lệnh chạy xa.
Sẽ có chuỗi thua liên tiếp và tháng lỗ. Không tín hiệu nào chắc chắn thắng — chỉ dùng vốn bạn chấp nhận mất.

<b>Lệnh</b>: /start /menu /phantich SOL /thongke /mode
Giá tham chiếu Binance Futures — giá ở sàn khác có thể lệch nhẹ."""
