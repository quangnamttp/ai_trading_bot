"""Tin tức tóm tắt tiếng Việt, tin nóng chỉ gửi khi đã dịch, kết luận 🔍 phân tích, danh sách coin khi Binance chặn."""
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app import alerts, newsread, reports, storage
from app.bot import handlers
from app.data import binance
from app.data.news import Headline


@pytest.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_engine", None)
    monkeypatch.setattr(storage, "settings", replace(storage.settings, database_url=f"sqlite+aiosqlite:///{tmp_path}/n.db",
                                                     private_mode=False, admin_ids=[1]))
    await storage.init()
    yield
    await storage.engine().dispose()
    storage._engine = None


def _h(title="Bitcoin hits new high", link="https://example.com/a"):
    return Headline(title, link, datetime.now(timezone.utc), 0.5, "Bitcoin rose 5% to a new record on ETF inflows.")


def test_format_summary():
    raw = "TIÊU ĐỀ: Bitcoin lập đỉnh mới\n- Giá tăng 5%.\n- Dòng tiền ETF vào mạnh.\nẢNH HƯỞNG: Tích cực cho BTC."
    text = newsread._format(raw, "10:00 25/09")
    assert "Bitcoin lập đỉnh mới" in text and "• Giá tăng 5%." in text and "Ảnh hưởng" in text
    assert newsread._format("không đúng định dạng", "x") is None


async def test_link_points_to_news_bot(db, monkeypatch):
    monkeypatch.setattr(reports, "NEWS_USERNAME", "news_bot")
    url = await newsread.link_for(_h())
    assert url.startswith("https://t.me/news_bot?start=nw_") and len(url.split("nw_")[1]) == 10
    monkeypatch.setattr(reports, "NEWS_USERNAME", "")
    assert await newsread.link_for(_h()) == "https://example.com/a"  # chưa biết tên bot -> link bài gốc


async def test_summary_uses_ai_and_caches(db, monkeypatch):
    calls = []

    async def ask(q, ctx, scope, **kw):
        calls.append(scope)
        return "TIÊU ĐỀ: Bitcoin lập đỉnh\n- Ý 1.\n- Ý 2.\nẢNH HƯỞNG: Nhỏ.", "x"

    async def page(url):
        return ""
    monkeypatch.setattr(newsread.ai, "enabled", lambda: True)
    monkeypatch.setattr(newsread.ai, "ask", ask)
    monkeypatch.setattr(newsread, "article_text", page)
    nid = await newsread.ref(_h())
    text, url = await newsread.summary(nid)
    assert "Bitcoin lập đỉnh" in text and url == "https://example.com/a"
    await newsread.summary(nid)
    assert calls == ["summary"]  # lần 2 lấy bản đã lưu
    assert await newsread.summary("khongco") is None


async def test_breaking_news_needs_vietnamese(db, monkeypatch):
    sent = []

    async def heads(hours):
        return [_h("Exchange hacked, $200M stolen", "https://example.com/hack")]

    async def rate(items):
        return {h.title: 9 for h in items}

    async def send(bot, text, markup=None, **kw):
        sent.append(text)
    monkeypatch.setattr(alerts.news, "headlines", heads)
    monkeypatch.setattr(alerts, "rate_headlines", rate)
    monkeypatch.setattr(reports, "broadcast_news", send)
    monkeypatch.setattr(newsread.ai, "enabled", lambda: False)
    await alerts.breaking_news(None)
    assert sent == []  # chưa dịch được -> chưa gửi, lần sau thử lại

    async def ask(q, ctx, scope, **kw):
        return "TIÊU ĐỀ: Sàn bị hack 200 triệu USD\n- Ý 1.\n- Ý 2.\nẢNH HƯỞNG: Xấu.", "x"

    async def page(url):
        return ""
    monkeypatch.setattr(newsread.ai, "enabled", lambda: True)
    monkeypatch.setattr(newsread.ai, "ask", ask)
    monkeypatch.setattr(newsread, "article_text", page)
    await alerts.breaking_news(None)
    await alerts.breaking_news(None)
    assert len(sent) == 1 and "Sàn bị hack" in sent[0]


def _res(score_long, vetoed=None):
    from app.strategy.core import Candidate
    row = {"entry": 100.0, "sl": 95.0, "atr4": 2.0, "raw": score_long, "trend": 30, "momentum": 10, "setup": 16,
           "flow": 10, "score": score_long, "setup_type": "retest",
           "btc_pts": 5, "fng_pts": 0, "fund_pts": 0}
    cand = Candidate("SOLUSDT", 1, score_long, row)
    cand.vetoed = vetoed
    coin = binance.Coin("SOLUSDT", "SOL", 1, 1e9, "SOLUSDT")
    return {"coin": coin, "candidate": cand, "rows": {1: row, -1: row | {"raw": 10}}, "deriv": {},
            "news": {"count": 0, "sentiment": 0}, "threshold": 75.0}


def test_analysis_verdict():
    ok = handlers.analysis_text(_res(80))
    assert "KẾT LUẬN: CÓ THỂ VÀO LONG" in ok and "SL" in ok and "Trailing" in ok and "TP1" not in ok
    assert "KẾT LUẬN: CHƯA NÊN VÀO" in handlers.analysis_text(_res(60))
    assert "bị chặn" in handlers.analysis_text(_res(80, vetoed="Funding quá nóng"))


async def test_universe_when_fallback_lacks_volume(monkeypatch):
    async def perps():
        return {"SOLUSDT", "AINUSDT"}

    async def spots():
        return set()

    async def tick():
        return {"SOLUSDT": {"quoteVolume": "1000"}}  # nguồn dự phòng không có AIN
    monkeypatch.setattr(binance, "perpetual_symbols", perps)
    monkeypatch.setattr(binance, "spot_symbols", spots)
    monkeypatch.setattr(binance, "tickers_24h", tick)
    assert [c.symbol for c in await binance.universe(10, 0)] == ["SOLUSDT", "AINUSDT"]


async def test_perps_fallback_excludes_stocks(db, monkeypatch):
    await storage.kv_set("binance_perps", "SOLUSDT,ETHUSDT")
    monkeypatch.setattr(binance, "_last_perps", set())

    async def fail(*a, **k):
        raise RuntimeError("429")

    async def bybit():
        return [{"symbol": "SOLUSDT"}, {"symbol": "ETHUSDT"}, {"symbol": "SOXLUSDT"}]
    monkeypatch.setattr(binance, "get_json", fail)
    monkeypatch.setattr(binance, "_bybit_instruments", bybit)
    assert await binance.perpetual_symbols() == {"SOLUSDT", "ETHUSDT"}


async def test_bybit_list_excludes_stocks(monkeypatch):
    async def gj(url, *a, **k):
        return {"result": {"list": [
            {"symbol": s, "status": "Trading", "contractType": "LinearPerpetual", "quoteCoin": "USDT", "symbolType": t}
            for s, t in (("SOLUSDT", ""), ("NEWUSDT", "innovation"), ("SOXLUSDT", "ETF"), ("TSLAUSDT", "stock"))]}}
    monkeypatch.setattr(binance, "get_json", gj)
    assert [i["symbol"] for i in await binance._bybit_instruments()] == ["SOLUSDT", "NEWUSDT"]


def test_waiting_plan():
    from app.strategy import waiting
    up = {1: {"trend": 30, "entry": 110.0, "atr4": 2.0}, -1: {"trend": 0, "entry": 110.0, "atr4": 2.0}}
    w = waiting.plan(up, ema20=100.0, supports=[95.0], resistances=[120.0])
    assert w.side == 1 and w.kind == "ema" and w.lo == pytest.approx(99.3) and w.hi == pytest.approx(100.6)
    assert w.sl == pytest.approx(99.3 - 1.6) and w.act > w.hi
    w = waiting.plan(up | {1: {"trend": 30, "entry": 97.0, "atr4": 2.0}}, ema20=100.0, supports=[95.0, 90.0], resistances=[])
    assert w.kind == "level" and w.lo == pytest.approx(94.5)  # đã thủng EMA20 -> hỗ trợ ngày gần nhất
    flat = {1: {"trend": 10, "entry": 100.0, "atr4": 2.0}, -1: {"trend": 5, "entry": 100.0, "atr4": 2.0}}
    assert waiting.plan(flat, 100.0, [], []).kind == "flat"
    down = {1: {"trend": 0, "entry": 100.0, "atr4": 2.0}, -1: {"trend": 30, "entry": 100.0, "atr4": 2.0}}
    assert waiting.plan(down, 105.0, [], [110.0], mode="spot").kind == "spot_down"
    w = waiting.plan(down, 105.0, [], [110.0])
    assert w.side == -1 and w.sl > w.hi and "SHORT" in "".join(waiting.lines(w, str))
