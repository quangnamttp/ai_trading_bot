from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app import ai, assistant, events, reports, storage
from app.strategy import levels
from app.strategy.trade import Trade


@pytest.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_engine", None)
    monkeypatch.setattr(storage, "settings", replace(storage.settings, database_url=f"sqlite+aiosqlite:///{tmp_path}/a.db",
                                                     private_mode=True, admin_ids=[1]))
    await storage.init()
    yield
    await storage.engine().dispose()
    storage._engine = None


# ---------------------------------------------------------------- chống lặp / bịa số
def test_degenerate_detects_loops():
    loop = "Thị trường đang tăng mạnh vì dòng tiền vào. " * 6
    assert ai.degenerate(loop)
    ok = ("BTC đang ở 64000 USD, tăng 2% trong 24 giờ. Fear & Greed 71 cho thấy thị trường tham lam. "
          "Tuần này có CPI vào thứ Tư, giá có thể biến động mạnh hai chiều quanh giờ ra tin.")
    assert not ai.degenerate(ok)


def test_invented_numbers():
    ctx = "BTC: 64000.00 USD (+2.10% 24h)\nChỉ số Fear & Greed hôm nay: 71/100 (Greed)"
    assert ai.invented_numbers("Fear & Greed đang là 71, BTC 64000", ctx) == 0
    assert ai.invented_numbers("Fear & Greed 40, BTC 58000, ETH 2500, SOL 150", ctx) >= 4


async def test_scope_codes_returned(monkeypatch):
    monkeypatch.setattr(ai, "settings", replace(ai.settings, gemini_key="k", groq_key="", openrouter_key=""))

    async def disc(provider, client):
        return ["m"]

    async def call(provider, model, system, prompt, client):
        return "OUT_OF_SCOPE"
    monkeypatch.setattr(ai, "_discover", disc)
    monkeypatch.setattr(ai, "_call", call)
    text, _ = await ai.ask("thời tiết hôm nay?", "ctx", "trade")
    assert text == ai.OUT_OF_SCOPE


async def test_out_of_scope_does_not_use_quota(db, monkeypatch):
    async def ask(q, ctx, scope):
        return ai.OUT_OF_SCOPE, "x"

    async def ctx(*a, **k):
        return "ctx"
    monkeypatch.setattr(assistant.ai, "ask", ask)
    monkeypatch.setattr(assistant, "market_context", ctx)
    text = await assistant.answer(5, "thời tiết hôm nay thế nào?")
    assert "crypto" in text
    assert (await assistant.allowed(5))[1] == 0

    async def ask_ok(q, ctx, scope):
        return "BTC đang đi ngang.", "x"
    monkeypatch.setattr(assistant.ai, "ask", ask_ok)
    await assistant.answer(5, "BTC thế nào?")
    assert (await assistant.allowed(5))[1] == 1


async def test_find_symbols(monkeypatch):
    async def perps():
        return {"SOLUSDT", "ETHUSDT", "1000PEPEUSDT", "HOTUSDT", "DOGEUSDT"}
    monkeypatch.setattr(assistant.binance, "perpetual_symbols", perps)
    assert await assistant.find_symbols("lập kế hoạch dca cho sol") == ["SOLUSDT"]
    assert await assistant.find_symbols("PEPE và ETH vào đâu?") == ["1000PEPEUSDT", "ETHUSDT"]
    assert await assistant.find_symbols("coin nào hot hôm nay, DCA thế nào") == []
    assert await assistant.find_symbols("PEPEUSDC trên MEXC") == ["1000PEPEUSDT"]


async def test_signal_by_message_and_quota_reset(db):
    now = storage.now()
    t = Trade(1, 100, 90, created=now, deadline=now + timedelta(days=7))
    sid = await storage.insert_signal(symbol="SOLUSDT", display="SOL/USDT", side=1, spot_symbol="SOLUSDT",
                                      multiplier=1, score=80, setup="retest", entry=100, sl=90, tp1=120, tp2=130,
                                      zone_lo=99, zone_hi=100, reasons=storage.dumps(["OI tăng"]), status="ACTIVE",
                                      state=storage.dumps({"trade": t.to_dict(), "last_ts": now}))
    await storage.add_message(sid, 7, 555)
    s = await storage.signal_by_message(7, 555)
    assert s["id"] == sid and await storage.signal_by_message(7, 556) is None
    line = assistant._signal_lines(s)
    assert "SOL/USDT LONG" in line and "OI tăng" in line
    u = await storage.upsert_user(9, "x")
    assert u["news_dm"] is False  # tin tức mặc định chỉ vào topic


# ---------------------------------------------------------------- mốc giá kế hoạch DCA
def _bars(n, freq, start=100.0, drift=0.001, seed=0):
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(drift, 0.02, n)))
    idx = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
                         "volume": rng.uniform(1, 2, n)}, index=idx)


def test_volume_profile_value_area():
    df = _bars(300, "4h")
    poc, vah, val = levels.volume_profile(df)
    assert df["low"].min() <= val <= poc <= vah <= df["high"].max()


def test_build_plan_levels_sorted():
    p = levels.build_plan(_bars(400, "1D"), _bars(540, "4h", seed=1))
    assert all(x < p["price"] for x, _ in p["supports"])
    assert all(x > p["price"] for x, _ in p["resistances"])
    sup = [x for x, _ in p["supports"]]
    assert sup == sorted(sup, reverse=True)
    if p["dca"]:
        assert abs(sum(w for *_, w in p["dca"]) - 1) < 1e-9
        assert p["stop"] < sup[-1]
    text = levels.plan_context({**p, "display": "SOL"})
    assert "KẾ HOẠCH DO BOT TÍNH" in text


# ---------------------------------------------------------------- tin tức
def test_event_brief():
    what, rule = events.brief(*events.classify("CPI m/m"))
    assert "lạm phát" in what and "Cao hơn dự báo → thường XẤU" in rule
    what, rule = events.brief(*events.classify("Federal Funds Rate"))
    assert "Fed" in what and rule


def test_mood_and_scenario():
    assert "chưa chọn hướng" in reports._mood(0.001)
    r = {"p0": 100.0, "hi": 101.0, "lo": 99.0, "chg": 0.01, "now": 101.0}
    assert "bẫy tăng" in reports._scenario(r)
    assert "bẫy giảm" in reports._scenario({**r, "chg": -0.01})


async def test_news_stages_once(db, monkeypatch):
    t = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=60)
    evs = [{"title": "CPI m/m", "time": t, "impact": "High", "forecast": "0.3%", "previous": "0.4%"},
           {"title": "Core CPI m/m", "time": t, "impact": "High", "forecast": "0.2%", "previous": "0.3%"}]
    sent = []

    async def high():
        return evs

    async def stats(kind):
        return None

    async def bn(bot, text, markup=None, **kw):
        sent.append(text)
    monkeypatch.setattr(reports.macro, "high_impact_events", high)
    monkeypatch.setattr(reports.events, "reaction_stats", stats)
    monkeypatch.setattr(reports, "broadcast_news", bn)
    await reports.macro_reminders(None)
    await reports.macro_reminders(None)
    assert len(sent) == 1  # 2 tin cùng giờ gộp 1 tin nhắn, không gửi lặp
    assert "CPI m/m, Core CPI m/m" in sent[0] and "còn khoảng 1 giờ" in sent[0]
    assert len(sent[0].splitlines()) <= 6
