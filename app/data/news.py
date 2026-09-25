"""Tin tức crypto miễn phí qua RSS (+ CryptoPanic nếu có token) và chấm sentiment bằng từ khóa.

Không dùng LLM để giữ chi phí 0đ. Tin tức chỉ dùng làm bộ lọc (chặn tín hiệu khi có tin xấu
nghiêm trọng về coin) và điều chỉnh nhẹ điểm, không tự tạo tín hiệu.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from calendar import timegm
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser

from app.config import settings
from app.data.http import get_json, get_text

log = logging.getLogger(__name__)

FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
    "https://bitcoinmagazine.com/.rss/full/",
    "https://cryptoslate.com/feed/",
    "https://www.theblock.co/rss.xml",
    "https://blockworks.co/feed",
    "https://cryptopotato.com/feed/",
    "https://u.today/rss",
    "https://www.newsbtc.com/feed/",
]

# Tin xấu nghiêm trọng -> chặn LONG coin liên quan 24h
SEVERE_NEG = r"hack(ed)?|exploit(ed)?|drain(ed)?|delist(s|ed|ing)?|rug ?pull|insolv|bankrupt|halt(s|ed)? withdrawals|sec (sues|charges)|lawsuit|fraud|attack(ed)?|stolen|breach"
SEVERE_POS = r"etf approv|listing on (binance|coinbase)|lists? .* on (binance|coinbase)|mainnet launch|partnership with"
NEG = r"crash|plunge|dump|sell-?off|bearish|liquidat|outflow|ban(s|ned)?|crackdown|fear|slump|tumble|decline|drop|fall"
POS = r"surge|soar|rally|bullish|inflow|record high|all-time high|ath|adopt|approv|upgrade|gain|jump|rise|climb|breakout"

NAMES = {
    "BTC": "bitcoin", "ETH": "ethereum|ether", "SOL": "solana", "XRP": "ripple|xrp", "BNB": "bnb|binance coin",
    "DOGE": "dogecoin", "ADA": "cardano", "AVAX": "avalanche", "LINK": "chainlink", "DOT": "polkadot",
    "TON": "toncoin|\\bton\\b", "SUI": "\\bsui\\b", "NEAR": "near protocol", "ARB": "arbitrum", "OP": "optimism",
    "LTC": "litecoin", "BCH": "bitcoin cash", "UNI": "uniswap", "AAVE": "aave", "PEPE": "pepe", "TRX": "tron",
    "HYPE": "hyperliquid", "ENA": "ethena", "WLD": "worldcoin", "TAO": "bittensor", "ZEC": "zcash",
}


@dataclass
class Headline:
    title: str
    link: str
    time: datetime
    score: float  # -1..1
    summary: str = ""  # đoạn mô tả trong RSS (dùng khi không tải được bài gốc để tóm tắt)


def score_text(text: str) -> float:
    t = text.lower()
    pos = len(re.findall(POS, t)) + 2 * len(re.findall(SEVERE_POS, t))
    neg = len(re.findall(NEG, t)) + 2 * len(re.findall(SEVERE_NEG, t))
    return 0.0 if pos + neg == 0 else (pos - neg) / (pos + neg)


def mentions(base: str, text: str) -> bool:
    pattern = rf"\b{re.escape(base)}\b"
    if base in NAMES:
        pattern += f"|{NAMES[base]}"
    return re.search(pattern, text, re.IGNORECASE) is not None


async def _rss(url: str) -> list[Headline]:
    try:
        feed = feedparser.parse(await get_text(url, ttl=900))
    except Exception as exc:  # noqa: BLE001
        log.debug("RSS %s lỗi: %s", url, exc)
        return []
    out = []
    for e in feed.entries[:40]:
        ts = e.get("published_parsed") or e.get("updated_parsed")
        if not ts:
            continue
        title = html.unescape(html.unescape(e.get("title", "")))  # một số RSS mã hóa 2 lần (&amp;#x27;)
        desc = re.sub(r"<[^>]+>", " ", e.get("summary", "") or "")
        out.append(Headline(title, e.get("link", ""), datetime.fromtimestamp(timegm(ts), timezone.utc), score_text(title),
                            re.sub(r"\s+", " ", html.unescape(desc)).strip()[:1500]))
    return out


async def _cryptopanic() -> list[Headline]:
    if not settings.cryptopanic_token:
        return []
    try:
        d = await get_json("https://cryptopanic.com/api/developer/v2/posts/",
                           {"auth_token": settings.cryptopanic_token, "public": "true"}, ttl=900)
    except Exception as exc:  # noqa: BLE001
        log.debug("CryptoPanic lỗi: %s", exc)
        return []
    out = []
    for p in d.get("results", []):
        v = p.get("votes", {})
        pos, neg = v.get("positive", 0) + v.get("important", 0), v.get("negative", 0) + v.get("toxic", 0)
        s = score_text(p["title"])
        if pos + neg >= 3:
            s = (s + (pos - neg) / (pos + neg)) / 2
        out.append(Headline(p["title"], p.get("url", ""), datetime.fromisoformat(p["published_at"].replace("Z", "+00:00")), s))
    return out


async def headlines(hours: int = 24) -> list[Headline]:
    results = await asyncio.gather(*(_rss(u) for u in FEEDS), _cryptopanic())
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    seen, out = set(), []
    for h in sorted((h for r in results for h in r), key=lambda h: h.time, reverse=True):
        key = h.title.lower()[:60]
        if h.time >= cutoff and key not in seen:
            seen.add(key)
            out.append(h)
    return out


def market_sentiment(items: list[Headline], hours: int = 12) -> float:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    scores = [h.score for h in items if h.time >= cutoff and h.score != 0]
    return sum(scores) / len(scores) if scores else 0.0


def coin_news(base: str, items: list[Headline]) -> dict:
    """Sentiment riêng của coin + tin cực xấu (để chặn LONG) / cực tốt (để chặn SHORT)."""
    related = [h for h in items if mentions(base, h.title)]
    severe_neg = [h for h in related if re.search(SEVERE_NEG, h.title, re.IGNORECASE)]
    severe_pos = [h for h in related if re.search(SEVERE_POS, h.title, re.IGNORECASE)]
    scores = [h.score for h in related if h.score != 0]
    return {
        "count": len(related),
        "sentiment": sum(scores) / len(scores) if scores else 0.0,
        "severe_negative": severe_neg[:3],
        "severe_positive": severe_pos[:3],
    }
