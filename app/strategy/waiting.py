"""📋 Kịch bản chờ: khi 🔍 phân tích kết luận CHƯA NÊN VÀO, gợi ý vùng giá nên chờ theo đúng setup của bot.

Bot chỉ có lời (backtest) khi vào lệnh đủ điều kiện, nên đây KHÔNG phải lệnh vào ngay hay lệnh chờ đặt sẵn:
- Chọn phía có xu hướng mạnh hơn (điểm xu hướng >= 20/30); cả 2 phía yếu -> đi ngang, đứng ngoài.
- Vùng chờ = vùng hồi về EMA20 khung 4H (đúng setup Pullback của bot: -0.35 … +0.3 ATR quanh EMA20).
  Giá đã thủng EMA20 -> vùng hỗ trợ / kháng cự ngày gần nhất (± 0.25 ATR).
- SL tham khảo = mép vùng - 0.8 ATR (mức rủi ro tối thiểu bot dùng), trailing kích hoạt ở +1R.
Mọi con số tính từ dữ liệu bot, không do AI tạo ra.
"""
from __future__ import annotations

from dataclasses import dataclass

MIN_TREND = 20.0


@dataclass
class Waiting:
    side: int            # 1 LONG / -1 SHORT / 0 đứng ngoài
    lo: float = 0.0
    hi: float = 0.0
    sl: float = 0.0
    act: float = 0.0
    kind: str = ""       # ema | level | in_zone | flat | spot_down
    source: str = ""


def plan(rows: dict[int, dict], ema20: float | None, supports: list[float], resistances: list[float],
         mode: str = "futures") -> Waiting:
    t_long, t_short = float(rows[1]["trend"]), float(rows[-1]["trend"])
    side = 1 if t_long >= t_short else -1
    if max(t_long, t_short) < MIN_TREND:
        return Waiting(0, kind="flat")
    if mode == "spot" and side < 0:
        return Waiting(0, kind="spot_down")
    r = rows[side]
    px, atr = float(r["entry"]), float(r["atr4"])
    if not atr or not ema20:
        return Waiting(0, kind="flat")
    s = side
    lo, hi = sorted((ema20 - s * 0.35 * atr, ema20 + s * 0.3 * atr))
    kind, source = "ema", "EMA20 khung 4H"
    beyond = (px - ema20) * s < -0.35 * atr        # giá đã đi ngược qua EMA20 -> xu hướng yếu đi
    if beyond:
        levels = [x for x in (supports if s > 0 else resistances) if (px - x) * s > 0]
        if not levels:
            return Waiting(0, kind="flat")
        lvl = max(levels) if s > 0 else min(levels)  # mốc gần giá nhất phía dưới (LONG) / trên (SHORT)
        lo, hi = lvl - 0.25 * atr, lvl + 0.25 * atr
        kind, source = "level", "vùng hỗ trợ ngày" if s > 0 else "vùng kháng cự ngày"
    elif lo <= px <= hi or (px - ema20) * s < 0.3 * atr:
        kind = "in_zone"
    edge = lo if s > 0 else hi
    sl = edge - s * 0.8 * atr
    mid = (lo + hi) / 2
    return Waiting(side, lo, hi, sl, mid + (mid - sl), kind, source)


def lines(w: Waiting, fmt, mode: str = "futures") -> list[str]:
    """Các dòng HTML hiển thị dưới KẾT LUẬN."""
    if w.kind == "flat":
        return ["\n📋 <b>Kịch bản</b>: chưa có xu hướng rõ — đứng ngoài, chờ bot báo khi thị trường chọn hướng."]
    if w.kind == "spot_down":
        return ["\n📋 <b>Kịch bản</b>: xu hướng đang GIẢM — Spot nên đứng ngoài, chưa mua thêm."]
    name = ("MUA" if mode == "spot" else "LONG") if w.side > 0 else "SHORT"
    up = w.side > 0
    wait = (f"• Giá đang ở vùng chờ <b>{fmt(w.lo)} – {fmt(w.hi)}</b> ({w.source}): chờ nến 1H đóng "
            f"{'bật lên' if up else 'giảm xuống'} kèm dòng tiền {'mua' if up else 'bán'} ủng hộ"
            if w.kind == "in_zone" else
            f"• Chờ giá {'hồi về' if w.kind == 'ema' else 'về'} vùng <b>{fmt(w.lo)} – {fmt(w.hi)}</b> ({w.source}) "
            f"rồi nến 1H đóng {'bật lên' if up else 'giảm xuống'}")
    return [f"\n📋 <b>Kịch bản chờ {name}</b> (tham khảo — chưa phải tín hiệu):", wait,
            f"• SL tham khảo <b>{fmt(w.sl)}</b> · trailing kích hoạt khoảng <b>{fmt(w.act)}</b>",
            f"• ❌ Hủy kịch bản nếu nến 4H đóng {'dưới' if up else 'trên'} <b>{fmt(w.sl)}</b>",
            "Không đặt lệnh chờ sẵn: bot chỉ gửi tín hiệu khi đủ điều kiện (giá vào, SL, trailing chính xác)."]


def context(w: Waiting, fmt=lambda x: f"{x:.6g}") -> str:
    """Bản chữ cho AI (không HTML)."""
    import re
    return re.sub(r"<[^>]+>", "", "\n".join(lines(w, fmt)))
