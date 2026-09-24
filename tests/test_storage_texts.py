from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app import storage
from app.bot import texts
from app.bot.handlers import normalize_symbol
from app.data.binance import split_symbol
from app.strategy.trade import Trade


@pytest.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_engine", None)
    monkeypatch.setattr(storage, "settings", replace(storage.settings, database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db"))
    await storage.init()
    yield
    await storage.engine().dispose()
    storage._engine = None


async def test_users_and_signals(db):
    u = await storage.upsert_user(1, "a")
    assert u["mode"] == "futures" and u["subscribed"]
    await storage.update_user(1, mode="spot")
    assert (await storage.get_user(1))["mode"] == "spot"

    now = storage.now()
    t = Trade(1, 100, 90, created=now, deadline=now + timedelta(days=7))
    sid = await storage.insert_signal(symbol="SOLUSDT", display="SOL/USDT", side=1, spot_symbol="SOLUSDT",
                                      multiplier=1, score=80, setup="retest", entry=100, sl=90, tp1=120, tp2=130,
                                      zone_lo=99, zone_hi=100, reasons=storage.dumps([]), status="ACTIVE",
                                      state=storage.dumps({"trade": t.to_dict(), "last_ts": now, "notified_stop": 90}))
    [row] = await storage.open_signals()
    state = storage.loads(row["state"])
    assert Trade.from_dict(state["trade"]) == t
    assert state["last_ts"] == now
    assert row["created_at"].tzinfo is not None
    assert await storage.last_signal_time("SOLUSDT") is not None
    await storage.update_signal(sid, status="CLOSED", result_r=1.5, closed_at=now)
    assert len(await storage.closed_signals(days=1)) == 1


def test_price_format():
    assert texts.price(84767.7) == "84,767.70"
    assert texts.price(4.742) == "4.742"
    assert texts.price(0.00001234) == "0.00001234"


def test_sizing_safe_leverage():
    size, lev = texts.sizing(100, 95, 0.5)  # SL 5%
    assert size == pytest.approx(10)  # 0.5% / 5% = 10% vốn
    assert lev == 10  # 0.5 / 0.05


def test_symbol_helpers():
    assert normalize_symbol("sol") == "SOLUSDT"
    assert normalize_symbol("BTC/USDT") == "BTCUSDT"
    assert split_symbol("1000PEPEUSDT") == ("PEPE", 1000)
    assert split_symbol("BTCUSDT") == ("BTC", 1)


def test_signal_message_spot_divides_multiplier():
    sig = dict(display="PEPE/USDT", side=1, multiplier=1000, entry=0.01, sl=0.009, tp1=0.012, tp2=0.013,
               zone_lo=0.0099, zone_hi=0.01, score=80, trend=30, setup_text="x", reasons=[],
               created_at=datetime.now(timezone.utc))
    spot = texts.signal_message(sig, mode="spot", risk_pct=0.5, stats=None)
    fut = texts.signal_message(sig, mode="futures", risk_pct=0.5, stats=None)
    assert "0.00001" in spot and "đòn bẩy" not in spot
    assert "0.012" in fut and "đòn bẩy" in fut


def test_webhook_secret_is_telegram_safe(monkeypatch):
    import re
    from dataclasses import replace as _replace

    import app.main as m
    monkeypatch.setattr(m, "settings", _replace(m.settings, webhook_secret="a+b/c=d!@#", telegram_token="1:x"))
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,256}", m.webhook_secret())


async def test_migration_adds_new_columns_and_keeps_data(tmp_path, monkeypatch):
    import sqlalchemy as sa

    url = f"sqlite+aiosqlite:///{tmp_path}/old.db"
    monkeypatch.setattr(storage, "_engine", None)
    monkeypatch.setattr(storage, "settings", replace(storage.settings, database_url=url))
    # schema cũ (chưa có cột style/tier)
    async with storage.engine().begin() as c:
        await c.execute(sa.text("CREATE TABLE users (chat_id BIGINT PRIMARY KEY, username VARCHAR(64), "
                                "mode VARCHAR(8) NOT NULL DEFAULT 'futures', risk_pct FLOAT NOT NULL DEFAULT 0.5, "
                                "subscribed BOOLEAN NOT NULL DEFAULT 1, banned BOOLEAN NOT NULL DEFAULT 0, "
                                "created_at DATETIME NOT NULL)"))
        await c.execute(sa.text("INSERT INTO users (chat_id, username, created_at) VALUES (7, 'cu', '2026-01-01')"))
    await storage.init()
    u = await storage.get_user(7)
    assert u["username"] == "cu" and u["style"] == "both"
    await storage.kv_set("a", "1")
    await storage.kv_set("a", "2")
    assert await storage.kv_get("a") == "2"
    await storage.engine().dispose()
    storage._engine = None
