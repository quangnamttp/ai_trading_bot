from dataclasses import replace
from datetime import timedelta

import pytest

from app import assistant, events, portfolio as pf, storage
from app.bot import handlers, texts
from app.strategy.trade import Trade


@pytest.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_engine", None)
    monkeypatch.setattr(storage, "settings", replace(storage.settings, database_url=f"sqlite+aiosqlite:///{tmp_path}/p.db",
                                                     private_mode=False, admin_ids=[1]))
    await storage.init()
    yield
    await storage.engine().dispose()
    storage._engine = None


# ---------------------------------------------------------------- giá vốn / lời lỗ
def test_apply_trade_average_and_realized():
    pos = {"qty": 1.0, "avg_price": 150.0, "invested": 150.0, "realized": 0.0}
    pos = {**pos, **storage.apply_trade(pos, "buy", 1.0, 100.0)}  # mua thêm 1 coin giá 100
    assert pos["qty"] == 2 and pos["avg_price"] == 125 and pos["invested"] == 250
    pos = {**pos, **storage.apply_trade(pos, "sell", 1.0, 135.0)}  # bán 1 coin giá 135 -> lời 10
    assert pos["qty"] == 1 and pos["avg_price"] == 125 and pos["realized"] == pytest.approx(10)
    pos = {**pos, **storage.apply_trade(pos, "sell", 5.0, 100.0)}  # bán quá số đang có -> chỉ bán phần còn
    assert pos["qty"] == 0 and pos["realized"] == pytest.approx(-15)


def test_parse_number_and_money():
    assert pf.parse_number("100") == 100
    assert pf.parse_number("1,5") == 1.5
    assert pf.parse_number("1,234.5") == 1234.5
    assert pf.parse_number("2tr", "VND") == 2_000_000
    assert pf.parse_number("500k", "VND") == 500_000
    assert pf.parse_number("2.500.000", "VND") == 2_500_000
    assert pf.parse_number("abc") is None
    assert pf.money(1234.5, "USDT", 1) == "1,234.50 USDT"
    assert pf.money(10, "VND", 26_000) == "260.000 đ"
    assert pf.money(-5, "USDT", 1, sign=True) == "−5.00 USDT"


def test_dca_due_alerts():
    plan = {"levels": [{"price": 100, "name": "VAL", "amount": 30, "status": "pending", "alerted": False},
                       {"price": 90, "name": "đáy", "amount": 70, "status": "pending", "alerted": False}],
            "stop": 80, "stop_alerted": False, "budget": 100}
    pos = {"plan": storage.dumps(plan), "budget": 100}
    assert pf.due_alerts(pos, 105, 106) == []
    assert pf.due_alerts(pos, 100.4, 101) == [("level", 0)]  # cách mốc <= 0.5% coi là chạm
    assert pf.due_alerts(pos, 89, 79) == [("level", 0), ("level", 1), ("stop", -1)]
    assert pf.remaining_budget(pos) == 100


async def test_portfolio_storage_and_scan_list(db):
    await storage.upsert_user(2, "a")
    await storage.update_user(2, mode="spot")
    assert await storage.add_position(2, "SOLUSDT")
    new = await pf.buy(2, "SOLUSDT", 300, 150)
    assert new["qty"] == 2 and new["avg_price"] == 150
    await pf.sell(2, "SOLUSDT", 1, 180)
    p = await storage.position(2, "SOLUSDT")
    assert p["qty"] == 1 and p["realized"] == pytest.approx(30)
    assert [t["side"] for t in await storage.trades_of(2, "SOLUSDT")] == ["sell", "buy"]
    # coin tự chọn dùng để quét: Spot -> danh mục; Futures -> coin theo dõi
    await storage.add_user_coin(2, "ETHUSDT")
    assert {r["symbol"] for r in await storage.all_user_coins()} == {"SOLUSDT"}
    await storage.update_user(2, mode="futures")
    assert {r["symbol"] for r in await storage.all_user_coins()} == {"ETHUSDT"}


async def test_holding_migrates_to_portfolio(db):
    await storage.upsert_user(3, "b")
    await storage.add_user_coin(3, "PEPEUSDT")
    await storage.toggle_holding(3, "PEPEUSDT")
    await storage.kv_set("migr:holding_to_portfolio", "")
    await storage.init()
    assert [p["symbol"] for p in await storage.portfolio_of(3)] == ["PEPEUSDT"]


# ---------------------------------------------------------------- AI theo chế độ
async def test_spot_ai_only_portfolio_coins(db, monkeypatch):
    async def perps():
        return {"SOLUSDT", "ETHUSDT", "BTCUSDT"}
    called = []

    async def ask(q, ctx, scope):
        called.append(scope)
        return "trả lời", "x"
    monkeypatch.setattr(assistant.binance, "perpetual_symbols", perps)
    monkeypatch.setattr(assistant.ai, "ask", ask)
    user = await storage.upsert_user(4, "c")
    await storage.update_user(4, mode="spot")
    user = await storage.get_user(4)
    text, buttons = await assistant.answer_personal(user, "nên DCA ETH không")
    assert "danh mục" in text.lower() and not called  # danh mục trống -> không gọi AI
    await storage.add_position(4, "SOLUSDT")
    text, buttons = await assistant.answer_personal(user, "nên DCA ETH không")
    assert "không có đầu tư đồng coin <b>ETH</b>" in text and not called
    assert buttons == [assistant.MARKET_BUTTON]
    assert (await assistant.allowed(4))[1] == 0  # không trừ lượt


async def test_futures_ai_only_own_open_signals(db, monkeypatch):
    async def perps():
        return {"SOLUSDT", "ETHUSDT"}
    monkeypatch.setattr(assistant.binance, "perpetual_symbols", perps)
    user = await storage.upsert_user(5, "d")
    text, _ = await assistant.answer_personal(user, "lệnh SOL khi nào về bờ")
    assert "không có lệnh đang mở" in text
    now = storage.now()
    ids = []
    for sym in ("SOLUSDT", "ETHUSDT"):
        t = Trade(1, 100, 90, created=now, deadline=now + timedelta(days=7))
        sid = await storage.insert_signal(symbol=sym, display=f"{sym[:3]}/USDT", side=1, spot_symbol=sym, multiplier=1,
                                          score=80, setup="retest", entry=100, sl=90, tp1=120, tp2=130, zone_lo=99,
                                          zone_hi=100, reasons=storage.dumps([]), status="ACTIVE", created_at=now,
                                          state=storage.dumps({"trade": t.to_dict(), "last_ts": now}))
        await storage.add_message(sid, 5, 100 + sid)
        ids.append(sid)
    text, buttons = await assistant.answer_personal(user, "lệnh của tôi thế nào")
    assert text == assistant.PICK_SIGNAL and {b[1] for b in buttons} == {f"aisig:{i}" for i in ids}
    await storage.update_signal(ids[0], status="CLOSED", result_r=-1.0, closed_at=now)
    text, _ = await assistant.answer_personal(user, "SOL sao rồi")
    assert "đã đóng" in text and "-1.00R" in text


# ---------------------------------------------------------------- tổng kết lệnh, menu, tên tin tiếng Việt
def test_close_summary_lessons():
    now = storage.now()
    t = Trade(1, 100, 90, created=now, deadline=now + timedelta(days=7))
    t.realized_r, t.outcome, t.max_r = -1.0, "SL", 0.1
    sig = {"display": "SOL/USDT", "side": 1}
    text = texts.close_summary(sig, t, risk_pct=0.5, hours=5, btc_chg=-0.04)
    assert "-1.00R" in text and "-0.50% vốn" in text and "ngược gần như ngay" in text and "BTC chạy ngược" in text
    t.realized_r, t.outcome, t.max_r = 1.8, "TRAIL", 2.5
    assert "đúng hướng" in texts.close_summary(sig, t, risk_pct=1, hours=30, btc_chg=None)


def test_menu_by_mode_and_role(monkeypatch):
    monkeypatch.setattr(handlers, "settings", replace(handlers.settings, admin_ids=[1]))
    def labels(m):
        return [b.text for row in m.keyboard for b in row]
    spot = labels(handlers.menu({"chat_id": 9, "mode": "spot"}))
    fut = labels(handlers.menu({"chat_id": 9, "mode": "futures"}))
    admin = labels(handlers.menu({"chat_id": 1, "mode": "futures"}))
    assert handlers.BTN_PORTFOLIO in spot and handlers.BTN_WATCH not in spot
    assert handlers.BTN_WATCH in fut and handlers.BTN_PORTFOLIO not in fut
    assert handlers.BTN_ADMIN in admin and handlers.BTN_ADMIN not in fut
    kb = handlers.mode_keyboard({"mode": "spot", "risk_pct": 0.5, "subscribed": True})
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "mode:spot" in datas and not any(d.startswith("style:") for d in datas)  # Spot ẩn Swing dài
    assert "newsdm" not in datas


def test_vi_titles():
    assert events.vi_title("Core CPI m/m") == "Lạm phát lõi CPI (so tháng trước)"
    assert events.vi_title("FOMC Member Waller Speaks") == "Thành viên Fed Waller phát biểu"
    assert events.vi_title("Something New") == "Something New"


async def test_vi_titles_translate_and_cache(db, monkeypatch):
    calls = []

    async def ask(q, ctx, scope):
        calls.append(scope)
        return "1. Bitcoin vượt 100 nghìn USD\n2. SEC duyệt quỹ ETF Solana", "x"
    monkeypatch.setattr(assistant.ai, "ask", ask)
    monkeypatch.setattr(assistant.ai, "enabled", lambda: True)
    assistant._vi_cache.clear()
    titles = ["Bitcoin tops $100K", "SEC approves Solana ETF"]
    assert await assistant.vi_titles(titles) == ["Bitcoin vượt 100 nghìn USD", "SEC duyệt quỹ ETF Solana"]
    assistant._vi_cache.clear()
    assert await assistant.vi_titles(titles) == ["Bitcoin vượt 100 nghìn USD", "SEC duyệt quỹ ETF Solana"]
    assert calls == ["translate"]  # lần 2 lấy bản đã lưu, không gọi AI
