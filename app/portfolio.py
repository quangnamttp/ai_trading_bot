"""💼 Danh mục Spot: định giá, lời/lỗ, kế hoạch DCA theo số tiền, cảnh báo khi giá chạm vùng DCA.

- Giá lấy từ Binance Futures (chia hệ số 1000 với coin kiểu 1000PEPE) -> giá 1 coin thật, tính bằng USDT.
- Mọi số tiền lưu bằng USDT; hiển thị USDT hoặc VND theo cài đặt từng người (tỉ giá USDT/VND miễn phí).
- Kế hoạch DCA được "chốt" khi người dùng đặt vốn: các mốc giá không tự nhảy theo thị trường, muốn đổi thì bấm
  🔄 Tính lại. Bot chỉ nhắc — người dùng tự mua trên sàn rồi bấm ✅ Đã mua để bot cập nhật danh mục.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app import storage
from app.data import binance, macro
from app.strategy import levels

log = logging.getLogger(__name__)

TOUCH = 0.005  # giá cách mốc DCA <= 0.5% coi là chạm


def mult_of(symbol: str) -> int:
    return binance.split_symbol(symbol)[1]


def base_of(symbol: str) -> str:
    return binance.split_symbol(symbol)[0]


async def prices(symbols: list[str]) -> dict[str, dict]:
    """{symbol: {"price": giá 1 coin thật, "chg24": % 24h}}."""
    tick = await binance.tickers_24h()
    out = {}
    for s in symbols:
        t = tick.get(s)
        if t:
            out[s] = {"price": float(t["lastPrice"]) / mult_of(s), "chg24": float(t["priceChangePercent"]) / 100}
    return out


# ---------------------------------------------------------------- tiền tệ
async def rate(currency: str) -> float | None:
    """Số đơn vị `currency` cho 1 USDT (USDT -> 1). None nếu không lấy được tỉ giá."""
    return 1.0 if currency != "VND" else await macro.usdt_vnd()


def money(usdt: float, currency: str, fx: float | None, *, sign: bool = False) -> str:
    """Định dạng số tiền theo đơn vị người dùng: 1,234.56 USDT · 32.800.000 đ."""
    if currency == "VND" and fx:
        v = usdt * fx
        txt = f"{abs(v):,.0f}".replace(",", ".") + " đ"
    else:
        v = usdt
        txt = f"{abs(v):,.2f} USDT"
    if sign:
        return ("+" if v >= 0 else "−") + txt
    return ("−" if v < 0 else "") + txt


def parse_number(text: str, currency: str = "USDT") -> float | None:
    """'100' · '1,5' · '2tr' · '500k' · '2.500.000' (VND) -> số. None nếu không đọc được."""
    t = text.strip().lower().replace(" ", "")
    m = re.fullmatch(r"([\d.,]+)(k|tr|m|triệu|trieu)?(đ|d|vnd|usdt|\$)?", t)
    if not m:
        return None
    num, unit = m.group(1), m.group(2)
    if currency == "VND" and not unit and re.fullmatch(r"\d{1,3}(\.\d{3})+", num):
        num = num.replace(".", "")  # 2.500.000 kiểu Việt Nam
    elif "," in num and "." in num:
        num = num.replace(",", "")  # 1,234.5
    else:
        num = num.replace(",", ".")  # 1,5 -> 1.5
    try:
        v = float(num)
    except ValueError:
        return None
    return v * {"k": 1e3, "tr": 1e6, "m": 1e6, "triệu": 1e6, "trieu": 1e6}.get(unit or "", 1)


# ---------------------------------------------------------------- định giá
def valuation(pos: dict, px: float | None) -> dict:
    qty, avg = pos.get("qty") or 0.0, pos.get("avg_price") or 0.0
    value = qty * px if px else 0.0
    cost = qty * avg
    return {"qty": qty, "avg": avg, "price": px, "value": value, "cost": cost, "pnl": value - cost,
            "pnl_pct": (px / avg - 1) if px and avg else None, "realized": pos.get("realized") or 0.0}


# ---------------------------------------------------------------- kế hoạch DCA
def plan_of(pos: dict) -> dict | None:
    return storage.loads(pos["plan"]) if pos.get("plan") else None


def remaining_budget(pos: dict) -> float:
    plan = plan_of(pos)
    if not plan:
        return pos.get("budget") or 0.0
    return sum(lv["amount"] for lv in plan["levels"] if lv["status"] == "pending")


async def make_plan(symbol: str, budget: float) -> dict:
    """Chia `budget` USDT vào các vùng hỗ trợ bot tính (30% / 30% / 40%), kèm mức dừng DCA."""
    p = await levels.coin_plan(symbol)
    m = mult_of(symbol)
    lv = [{"price": price / m, "name": name, "amount": round(budget * w, 2), "status": "pending", "alerted": False}
          for price, name, w in p["dca"]]
    return {"created": datetime.now(timezone.utc).isoformat(), "levels": lv, "stop": p["stop"] / m,
            "stop_alerted": False, "trend": p["trend"], "budget": budget}


async def set_budget(chat_id: int, symbol: str, budget: float) -> dict:
    plan = await make_plan(symbol, budget) if budget > 0 else None
    await storage.update_position(chat_id, symbol, budget=budget, plan=storage.dumps(plan) if plan else None)
    return plan


async def replan(chat_id: int, symbol: str) -> dict | None:
    """Tính lại các mốc với số vốn DCA còn lại (các mốc đã mua giữ nguyên trong lịch sử)."""
    pos = await storage.position(chat_id, symbol)
    left = remaining_budget(pos)
    return await set_budget(chat_id, symbol, left) if left > 0 else None


async def mark_level(chat_id: int, symbol: str, i: int, status: str) -> dict | None:
    pos = await storage.position(chat_id, symbol)
    plan = plan_of(pos) if pos else None
    if not plan or not 0 <= i < len(plan["levels"]):
        return None
    plan["levels"][i]["status"] = status
    await storage.update_position(chat_id, symbol, plan=storage.dumps(plan))
    return plan["levels"][i]


MATCH = 0.02  # tự mua trong khoảng 2% quanh mốc DCA đang chờ -> coi như đã mua mốc đó


async def match_level(chat_id: int, symbol: str, price: float) -> int | None:
    """Người dùng tự ghi mua (không qua nút nhắc DCA): giá mua gần / dưới mốc DCA đang chờ -> đánh dấu mốc đó ✅
    (mốc cao nhất phù hợp), để bot không nhắc lại. Trả chỉ số mốc hoặc None."""
    pos = await storage.position(chat_id, symbol)
    plan = plan_of(pos) if pos else None
    if not plan:
        return None
    hits = [i for i, lv in enumerate(plan["levels"]) if lv["status"] == "pending" and price <= lv["price"] * (1 + MATCH)]
    if not hits:
        return None
    i = min(hits, key=lambda k: plan["levels"][k]["price"] - price if plan["levels"][k]["price"] >= price else 1e18)
    await mark_level(chat_id, symbol, i, "done")
    return i


async def buy(chat_id: int, symbol: str, amount_usdt: float, price: float, *, currency: str = "USDT",
              note: str | None = None) -> dict:
    return await storage.record_trade(chat_id, symbol, "buy", amount_usdt / price, price, currency=currency, note=note)


async def sell(chat_id: int, symbol: str, qty: float, price: float, *, currency: str = "USDT") -> dict:
    return await storage.record_trade(chat_id, symbol, "sell", qty, price, currency=currency)


def due_alerts(pos: dict, px: float, daily_close: float | None) -> list[tuple[str, int]]:
    """Các cảnh báo cần gửi: ("level", i) khi giá chạm mốc DCA chưa báo; ("stop", -1) khi nến ngày đóng dưới mức dừng."""
    plan = plan_of(pos)
    if not plan:
        return []
    out = []
    for i, lv in enumerate(plan["levels"]):
        if lv["status"] == "pending" and not lv["alerted"] and px <= lv["price"] * (1 + TOUCH):
            out.append(("level", i))
    if daily_close is not None and daily_close < plan["stop"] and not plan.get("stop_alerted"):
        out.append(("stop", -1))
    return out


def context_text(pos: dict, px: float | None, currency: str, fx: float | None) -> str:
    """Tóm tắt vị thế cho AI (số liệu thật, AI không cần đoán)."""
    v = valuation(pos, px)
    base = base_of(pos["symbol"])
    lines = [f"VỊ THẾ SPOT CỦA NGƯỜI HỎI – {base}:"]
    if v["qty"] > 0:
        lines.append(f"- Đang giữ {v['qty']:.6g} {base}, giá vốn TB {v['avg']:.6g} USDT, giá hiện tại "
                     f"{px:.6g} USDT" if px else f"- Đang giữ {v['qty']:.6g} {base}, giá vốn TB {v['avg']:.6g} USDT")
        lines.append(f"- Giá trị {money(v['value'], currency, fx)}, lời/lỗ {money(v['pnl'], currency, fx, sign=True)}"
                     + (f" ({v['pnl_pct']:+.1%})" if v["pnl_pct"] is not None else ""))
    else:
        lines.append("- Chưa ghi lệnh mua nào (số lượng 0).")
    if v["realized"]:
        lines.append(f"- Lời/lỗ đã chốt: {money(v['realized'], currency, fx, sign=True)}")
    plan = plan_of(pos)
    if plan:
        lines.append(f"- Vốn DCA dự kiến {money(plan['budget'], currency, fx)}, còn chưa giải ngân "
                     f"{money(remaining_budget(pos), currency, fx)}. Các mốc DCA đã chốt:")
        st = {"pending": "chờ", "done": "đã mua", "skipped": "bỏ qua"}
        for i, lv in enumerate(plan["levels"], 1):
            lines.append(f"  {i}. {lv['price']:.6g} USDT ({lv['name']}): {money(lv['amount'], currency, fx)} – {st[lv['status']]}")
        lines.append(f"- Dừng DCA / xem lại nếu nến ngày đóng dưới {plan['stop']:.6g} USDT")
    else:
        lines.append("- Chưa đặt vốn DCA (người dùng có thể bấm 🎯 Đặt vốn DCA trong 💼 Danh mục).")
    return "\n".join(lines)


async def summary_line(chat_id: int, currency: str) -> str | None:
    """💼 Danh mục: giá trị · lời/lỗ so với vốn · thay đổi 24h (cho báo cáo 22h)."""
    pos = [p for p in await storage.portfolio_of(chat_id) if (p.get("qty") or 0) > 0]
    if not pos:
        return None
    fx = await rate(currency)
    if currency == "VND" and not fx:
        currency, fx = "USDT", 1.0
    px = await prices([p["symbol"] for p in pos])
    value = cost = day = 0.0
    for p in pos:
        info = px.get(p["symbol"])
        if not info:
            continue
        v = p["qty"] * info["price"]
        value += v
        cost += p["qty"] * p["avg_price"]
        day += v - v / (1 + info["chg24"])
    pnl = value - cost
    return (f"💼 <b>Danh mục Spot</b>: {money(value, currency, fx)} · lời/lỗ {money(pnl, currency, fx, sign=True)}"
            + (f" ({pnl / cost:+.1%})" if cost else "") + f" · 24h {money(day, currency, fx, sign=True)}")
