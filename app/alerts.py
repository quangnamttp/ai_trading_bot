"""Cảnh báo sớm cho 📰 Bot Tin tức — chỉ những gì có thể đổi xu hướng / làm coin chạy mạnh:

- 🚀 Dấu hiệu sớm của coin (backtest 2 năm / 40 coin, cả 2 nửa dữ liệu đều đúng):
    • Gom hàng: OI +>=8% trong 4 giờ, giá gần như đứng yên (±2%), volume 4 giờ >= 2x trung bình
      -> 43% lần giá chạy >= 10% trong 24h (bình thường 15%), đỉnh TB +16%.
    • Ép short: funding âm, OI 24h +>=10%, tỉ lệ long/short <= 1 (short đông), giá 24h CHƯA chạy quá ±10%
      -> 42% lần chạy >= 10% trong 24h (bình thường 15%) — báo trước khi bay, không báo coin đã chạy xong.
  Báo có ảnh (nến + volume + OI) + nút mở 🔍 phân tích ở Bot Tín hiệu.
- 🆕 Niêm yết: Binance "Will List", Upbit thêm vào sàn KRW (thường làm giá bay trong vài phút).
- 💰 Tiền vào: tổng USDT + USDC tăng >= 1 tỉ USD trong 24h (tiền mới chuẩn bị mua).
- ⚡ Tin nóng: AI chấm mức ảnh hưởng tin mới 1–5, chỉ gửi mức 5 (Fed / bơm thanh khoản / ETF lớn / sàn lớn sập...).
Mỗi loại có giới hạn số tin mỗi ngày để không loãng.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from html import escape

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from app import chart, reports, storage
from app.bot import texts
from app.config import VN_TZ, settings
from app.data import binance, bybit, news
from app.data.http import get_json

log = logging.getLogger(__name__)

EARLY_OI4, EARLY_PX4, EARLY_VOLX = 0.08, 0.02, 2.0
SQUEEZE_OI24, SQUEEZE_LS, SQUEEZE_MAX_RUN = 0.10, 1.0, 0.10
MAX_PER_DAY = {"early": 5, "listing": 5, "money": 2, "breaking": 3}


def _day() -> str:
    return datetime.now(VN_TZ).strftime("%Y%m%d")


async def _quota(kind: str) -> bool:
    """Còn lượt gửi loại tin này hôm nay không (chống loãng)."""
    n = int(await storage.kv_get(f"alerts:{kind}:{_day()}") or 0)
    if n >= MAX_PER_DAY[kind]:
        return False
    await storage.kv_set(f"alerts:{kind}:{_day()}", str(n + 1))
    return True


async def _once(key: str) -> bool:
    if await storage.kv_get(key):
        return False
    await storage.kv_set(key, "1")
    return True


def _analyze_button(base: str) -> InlineKeyboardMarkup | None:
    url = reports.analyze_url(base)
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"🔍 {base}: có nên vào không? (Bot Tín hiệu)", url=url)]]) if url else None


# ---------------------------------------------------------------- 🚀 gom hàng / ép short
def detect(k1h, oi, ls: float | None, funding: float | None) -> list[str]:
    """Trả các dấu hiệu đang có: 'early' (gom hàng) / 'squeeze' (ép short). `k1h` nến 1H đã đóng, `oi` chuỗi OI 1h."""
    out = []
    if len(k1h) < 130 or oi is None or len(oi) < 25:
        return out
    c, v = k1h["close"], k1h["volume"]
    ch4 = float(c.iloc[-1] / c.iloc[-5] - 1)
    vol4 = float(v.iloc[-4:].sum())
    vol_avg = float(v.iloc[-124:-4].mean()) * 4
    oi4 = float(oi.iloc[-1] / oi.iloc[-5] - 1)
    oi24 = float(oi.iloc[-1] / oi.iloc[-25] - 1)
    if oi4 >= EARLY_OI4 and abs(ch4) <= EARLY_PX4 and vol_avg > 0 and vol4 / vol_avg >= EARLY_VOLX:
        out.append("early")
    ch24 = float(c.iloc[-1] / c.iloc[-25] - 1)
    if (funding is not None and funding < 0 and oi24 >= SQUEEZE_OI24 and ls is not None and ls <= SQUEEZE_LS
            and abs(ch24) <= SQUEEZE_MAX_RUN):
        out.append("squeeze")
    return out


async def early_signals(bot: Bot) -> None:
    coins = [c for c in await binance.universe(50, settings.min_quote_volume) if c.symbol != "BTCUSDT"]
    fund = await binance.all_funding()
    now = int(time.time() * 1000)
    for c in coins:
        try:
            k = await binance.klines(c.symbol, "1h", 150)
            oi, ls = await asyncio.gather(bybit.open_interest(c.symbol, now - 30 * 3_600_000, now, "1h"),
                                          bybit.long_short(c.symbol, now - 30 * 3_600_000, now, "1h"))
        except Exception as exc:  # noqa: BLE001
            log.debug("dấu hiệu sớm %s: %s", c.symbol, exc)
            continue
        found = detect(k, oi, float(ls.iloc[-1]) if len(ls) else None, fund.get(c.symbol))
        for kind in found:
            if not await _once(f"early:{c.symbol}:{kind}:{_day()}{datetime.now(VN_TZ).hour // 12}"):
                continue
            if not await _quota("early"):
                return
            await _send_early(bot, c, kind, k, oi, float(ls.iloc[-1]) if len(ls) else None, fund.get(c.symbol))


async def _send_early(bot: Bot, c, kind: str, k, oi, ls: float | None, funding: float | None) -> None:
    px = float(k["close"].iloc[-1]) / c.multiplier
    ch4 = float(k["close"].iloc[-1] / k["close"].iloc[-5] - 1)
    ch24 = float(k["close"].iloc[-1] / k["close"].iloc[-25] - 1)
    oi4, oi24 = float(oi.iloc[-1] / oi.iloc[-5] - 1), float(oi.iloc[-1] / oi.iloc[-25] - 1)
    volx = float(k["volume"].iloc[-4:].sum()) / max(1e-9, float(k["volume"].iloc[-124:-4].mean()) * 4)
    if kind == "early":
        head = f"🚀 <b>{escape(c.base)}</b> · dấu hiệu gom hàng"
        body = f"OI +{oi4:.0%} trong 4 giờ · volume x{volx:.1f} · giá mới {ch4:+.1%} (24h {ch24:+.1%})"
        stat = "📊 2 năm qua: 43% lần giá chạy ≥10% trong 24h sau dấu hiệu này (bình thường 15%)"
    else:
        head = f"🚀 <b>{escape(c.base)}</b> · dễ bị ép short"
        body = f"Funding {funding:.3%} (phe short trả phí) · OI 24h +{oi24:.0%} · giá 24h {ch24:+.1%}"
        stat = "📊 2 năm qua: 42% lần giá chạy ≥10% trong 24h sau dấu hiệu này (bình thường 15%)"
    extra = [f"Giá {texts.price(px)}"] + ([f"Long/Short {ls:.2f}"] if ls else [])
    text = "\n".join([head, body, " · ".join(extra), stat])
    try:  # OI dài hơn cho ảnh (4 ngày)
        now = int(time.time() * 1000)
        oi_img = await bybit.open_interest(c.symbol, now - 100 * 3_600_000, now, "1h")
        oi = oi_img if len(oi_img) > len(oi) else oi
    except Exception:  # noqa: BLE001
        pass
    photo = await asyncio.to_thread(chart.render_flow, k, oi, title=f"{c.base} · {'gom hàng' if kind == 'early' else 'ép short'}",
                                    subtitle=body.replace("<b>", "").replace("</b>", ""))
    await reports.broadcast_news(bot, text, _analyze_button(c.base), category="early", photo=photo)


# ---------------------------------------------------------------- 🆕 niêm yết sàn lớn
BINANCE_LIST = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
UPBIT_LIST = "https://api-manager.upbit.com/api/v1/announcements"


async def listings(bot: Bot) -> None:
    items: list[tuple[str, str, str]] = []  # (mã, sàn, tiêu đề)
    try:
        data = await get_json(BINANCE_LIST, {"type": 1, "catalogId": 48, "pageNo": 1, "pageSize": 10}, ttl=240, retries=1)
        for a in data["data"]["catalogs"][0]["articles"]:
            t = a["title"]
            if re.search(r"Binance Will List", t) and time.time() * 1000 - a["releaseDate"] < 6 * 3_600_000:
                for tick in re.findall(r"\(([A-Z0-9]{2,12})\)", t):
                    items.append((tick, "Binance", t))
    except Exception as exc:  # noqa: BLE001
        log.debug("Binance listing: %s", exc)
    try:
        data = await get_json(UPBIT_LIST, {"os": "web", "page": 1, "per_page": 20, "category": "trade"}, ttl=240, retries=1)
        for n in data["data"]["notices"]:
            t = n["title"]
            listed = datetime.fromisoformat(n["listed_at"]).astimezone(timezone.utc)
            if "디지털 자산 추가" in t and "원화" in t and datetime.now(timezone.utc) - listed < timedelta(hours=6):
                for tick in re.findall(r"\(([A-Z0-9]{2,12})\)", t):
                    items.append((tick, "Upbit (KRW)", t))
    except Exception as exc:  # noqa: BLE001
        log.debug("Upbit listing: %s", exc)
    perps = await binance.perpetual_symbols()
    for tick, ex, title in items:
        if not await _once(f"listing:{ex}:{tick}"):
            continue
        if not await _quota("listing"):
            return
        sym = f"{tick}USDT" if f"{tick}USDT" in perps else f"1000{tick}USDT" if f"1000{tick}USDT" in perps else None
        text = (f"🆕 <b>{escape(tick)} sắp niêm yết trên {ex}</b>\n{escape(title[:140])}\n"
                "Tin niêm yết sàn lớn thường làm giá biến động rất mạnh trong vài phút đến vài giờ.")
        photo = None
        if sym:
            try:
                k = await binance.klines(sym, "1h", 96)
                photo = await asyncio.to_thread(chart.render_flow, k, None, title=f"{tick} · niêm yết {ex}")
            except Exception:  # noqa: BLE001
                photo = None
        await reports.broadcast_news(bot, text, _analyze_button(tick) if sym else None, category="listing",
                                     photo=photo, silent=False)


# ---------------------------------------------------------------- 💰 stablecoin phát hành lớn
async def stablecoin_flow(bot: Bot) -> None:
    try:
        data = await get_json("https://stablecoins.llama.fi/stablecoins", {"includePrices": "false"}, ttl=1800, retries=1)
    except Exception as exc:  # noqa: BLE001
        log.debug("stablecoin: %s", exc)
        return
    chg, parts = 0.0, []
    for a in data.get("peggedAssets", []):
        if a.get("symbol") in ("USDT", "USDC"):
            now = float(a["circulating"].get("peggedUSD") or 0)
            prev = float(a["circulatingPrevDay"].get("peggedUSD") or 0)
            d = now - prev
            chg += d
            parts.append(f"{a['symbol']} {d / 1e9:+.2f} tỉ")
    if abs(chg) < 1e9 or not await _once(f"money:{_day()}:{chg > 0}"):
        return
    if not await _quota("money"):
        return
    text = (f"💰 <b>{'Tiền mới vào' if chg > 0 else 'Tiền rút ra'}: stablecoin {chg / 1e9:+.2f} tỉ USD trong 24h</b>\n"
            f"{' · '.join(parts)}\n"
            + ("Stablecoin phát hành thêm thường là tiền chuẩn bị mua vào thị trường." if chg > 0
               else "Stablecoin bị rút mạnh thường báo hiệu tiền rời thị trường."))
    await reports.broadcast_news(bot, text, category="money", silent=False)


# ---------------------------------------------------------------- ⚡ tin nóng (AI chấm mức ảnh hưởng)
KEY_5 = (r"\bfed\b.*\b(cut|hike|emergency)|rate (cut|hike)|quantitative easing|\bqe\b|liquidity injection|"
         r"etf (approved|approval)|approves? .*etf|bankrupt|insolv|halts? withdrawals|"
         r"hack(ed)?.*\$\d{3,}\s?(m|million)|\$\d+(\.\d+)?\s?b(illion)? (hack|exploit)|sec (sues|charges) .*(binance|coinbase)")


def _hid(title: str) -> str:
    return hashlib.sha1(title.lower().encode()).hexdigest()[:24]


async def rate_headlines(items: list) -> dict[str, int]:
    """Mức ảnh hưởng 1–5 của từng tiêu đề (AI chấm cả loạt, lưu lại; AI lỗi -> dùng từ khóa)."""
    from app import ai
    out, todo = {}, []
    for h in items:
        saved = await storage.kv_get(f"imp:{_hid(h.title)}")
        if saved:
            out[h.title] = int(saved)
        else:
            todo.append(h)
    if todo:
        scores: dict[int, int] = {}
        if ai.enabled():
            prompt = "\n".join(f"{i}. {h.title}" for i, h in enumerate(todo, 1))
            text, _ = await ai.ask("Chấm mức ảnh hưởng tới TOÀN thị trường crypto cho từng tiêu đề (1–5). "
                                   "5 = có thể đổi xu hướng: Fed / lãi suất bất ngờ, bơm thanh khoản, ETF lớn, sàn lớn sập "
                                   "hoặc bị hack rất lớn, quy định lớn của Mỹ/Trung Quốc. 4 = quan trọng với nhiều coin. "
                                   "1–3 = tin thường. Trả đúng mỗi dòng dạng 'số. điểm'.\n" + prompt, "", "rank")
            for m in re.finditer(r"^\s*(\d+)[.)]\s*([1-5])\b", text or "", re.M):
                scores[int(m.group(1))] = int(m.group(2))
        for i, h in enumerate(todo, 1):
            s = scores.get(i) or (5 if re.search(KEY_5, h.title, re.I) else 4 if abs(h.score) >= 0.6 else 2)
            out[h.title] = s
            await storage.kv_set(f"imp:{_hid(h.title)}", str(s))
    return out


async def breaking_news(bot: Bot) -> None:
    items = await news.headlines(3)
    if not items:
        return
    rated = await rate_headlines(items)
    for h in items:
        if rated.get(h.title, 0) < 5 or not await _once(f"breaking:{_hid(h.title[:60])}"):
            continue
        if not await _quota("breaking"):
            return
        from app.assistant import vi_titles
        vi = (await vi_titles([h.title]))[0]
        await reports.broadcast_news(bot, f"⚡ <b>Tin nóng</b> · {h.time.astimezone(VN_TZ):%H:%M}\n"
                                          f"<a href=\"{escape(h.link)}\">{escape(vi[:160])}</a>",
                                     category="breaking", silent=False)
