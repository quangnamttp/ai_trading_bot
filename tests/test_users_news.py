from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app import ai, events, reports, storage
from app.service import receives


@pytest.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_engine", None)
    monkeypatch.setattr(storage, "settings", replace(storage.settings, database_url=f"sqlite+aiosqlite:///{tmp_path}/u.db",
                                                     private_mode=True, admin_ids=[1]))
    await storage.init()
    yield
    await storage.engine().dispose()
    storage._engine = None


def user(**kw):
    base = {"mode": "futures", "style": "both", "coin_mode": "top"}
    return {**base, **kw}


def sig(**kw):
    base = {"symbol": "SOLUSDT", "side": 1, "spot_symbol": "SOLUSDT", "style": "short", "source": "top"}
    return {**base, **kw}


def test_receives_by_coin_mode():
    mine = {"PEPEUSDT"}
    top_sig, user_sig = sig(), sig(symbol="PEPEUSDT", source="user")
    assert receives(user(coin_mode="top"), top_sig, mine)
    assert not receives(user(coin_mode="top"), user_sig, mine)
    assert not receives(user(coin_mode="mine"), top_sig, mine)
    assert receives(user(coin_mode="mine"), user_sig, mine)
    assert receives(user(coin_mode="both"), top_sig, mine) and receives(user(coin_mode="both"), user_sig, mine)
    # coin trong Top 20 mà người dùng cũng tự chọn -> chế độ "chỉ coin của tôi" vẫn nhận
    assert receives(user(coin_mode="mine"), sig(symbol="PEPEUSDT", source="top"), mine)


def test_receives_spot_rules():
    assert not receives(user(mode="spot"), sig(side=-1))
    assert not receives(user(mode="spot"), sig(style="long"))
    assert receives(user(mode="spot"), sig())
    assert not receives(user(style="short"), sig(style="long"))


async def test_private_mode_and_user_coins(db):
    admin = await storage.upsert_user(1, "admin")
    stranger = await storage.upsert_user(2, "la", "Người Lạ")
    assert admin["approved"] and not stranger["approved"]
    assert [u["chat_id"] for u in await storage.subscribers()] == [1]
    await storage.update_user(2, approved=True)
    assert {u["chat_id"] for u in await storage.subscribers()} == {1, 2}
    assert await storage.add_user_coin(2, "PEPEUSDT")
    assert not await storage.add_user_coin(2, "PEPEUSDT")
    await storage.toggle_holding(2, "PEPEUSDT")
    [c] = await storage.user_coins_of(2)
    assert c["holding"]
    assert [r["symbol"] for r in await storage.all_user_coins()] == ["PEPEUSDT"]
    await storage.update_user(2, banned=True)
    assert await storage.all_user_coins() == []  # người bị chặn không còn được quét coin
    assert await storage.kv_incr("x") == 1 and await storage.kv_incr("x") == 2


def test_event_classify_and_calendar():
    assert events.classify("Core CPI m/m")[0] == "cpi"
    assert events.classify("Non-Farm Employment Change")[0] == "nfp"
    assert events.classify("Federal Funds Rate")[0] == "fomc"
    assert events.classify("Something Else")[0] == "other"
    t = datetime(2026, 9, 29, 12, 30, tzinfo=timezone.utc)
    evs = [{"title": "CPI m/m", "time": t, "impact": "High", "forecast": "0.3%"},
           {"title": "Unemployment Claims", "time": t + timedelta(days=1), "impact": "Medium", "forecast": "220K"}]
    text, markup = reports.calendar_message(evs, "Lịch")
    assert "CPI m/m" in text and "19:30" in text  # giờ VN
    assert all(len(b.callback_data) <= 64 for row in markup.inline_keyboard for b in row)


async def test_ai_without_keys_returns_none(monkeypatch):
    monkeypatch.setattr(ai, "settings", replace(ai.settings, gemini_key="", groq_key="", openrouter_key=""))
    text, reason = await ai.ask("hi", "ctx")
    assert text is None and "key" in reason
