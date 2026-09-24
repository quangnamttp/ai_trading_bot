"""Lưu trữ: SQLite (local) hoặc Postgres (Neon free — Render xóa ổ đĩa mỗi lần khởi động lại)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings

meta = sa.MetaData()

users = sa.Table(
    "users", meta,
    sa.Column("chat_id", sa.BigInteger, primary_key=True),
    sa.Column("username", sa.String(64)),
    sa.Column("mode", sa.String(8), nullable=False, server_default="futures"),  # spot | futures
    sa.Column("risk_pct", sa.Float, nullable=False, server_default="0.5"),
    sa.Column("style", sa.String(8), nullable=False, server_default="both"),  # short | long | both
    sa.Column("coin_mode", sa.String(8), nullable=False, server_default="top"),  # top | mine | both
    sa.Column("news_dm", sa.Boolean, nullable=False, server_default=sa.false()),  # nhận tin tức ở chat riêng
    sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.true()),  # người cũ tự được duyệt
    sa.Column("full_name", sa.String(128)),
    sa.Column("currency", sa.String(8), nullable=False, server_default="USDT"),  # đơn vị hiển thị: USDT | VND
    sa.Column("subscribed", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column("admin_muted", sa.Boolean, nullable=False, server_default=sa.false()),  # admin tạm dừng tín hiệu
    sa.Column("banned", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

watchlist = sa.Table(
    "watchlist", meta,
    sa.Column("symbol", sa.String(32), primary_key=True),
    sa.Column("added_by", sa.BigInteger),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

signals = sa.Table(
    "signals", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("symbol", sa.String(32), nullable=False, index=True),
    sa.Column("display", sa.String(32), nullable=False),
    sa.Column("side", sa.SmallInteger, nullable=False),
    sa.Column("spot_symbol", sa.String(32)),
    sa.Column("multiplier", sa.Integer, nullable=False, server_default="1"),
    sa.Column("score", sa.Float, nullable=False),
    sa.Column("setup", sa.String(16), nullable=False),
    sa.Column("style", sa.String(8), nullable=False, server_default="short"),  # short | long
    sa.Column("tier", sa.String(2), nullable=False, server_default="A"),
    sa.Column("source", sa.String(8), nullable=False, server_default="top"),  # top | user (coin tự chọn)
    sa.Column("entry", sa.Float, nullable=False),
    sa.Column("sl", sa.Float, nullable=False),
    sa.Column("tp1", sa.Float, nullable=False),
    sa.Column("tp2", sa.Float, nullable=False),
    sa.Column("zone_lo", sa.Float, nullable=False),
    sa.Column("zone_hi", sa.Float, nullable=False),
    sa.Column("reasons", sa.Text, nullable=False),
    sa.Column("state", sa.Text, nullable=False),  # Trade.to_dict() dạng JSON
    sa.Column("status", sa.String(12), nullable=False, index=True),  # ACTIVE / CLOSED
    sa.Column("result_r", sa.Float),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("closed_at", sa.DateTime(timezone=True)),
)

signal_messages = sa.Table(
    "signal_messages", meta,
    sa.Column("signal_id", sa.Integer, nullable=False, index=True),
    sa.Column("chat_id", sa.BigInteger, nullable=False),
    sa.Column("message_id", sa.BigInteger, nullable=False),
)


user_coins = sa.Table(
    "user_coins", meta,
    sa.Column("chat_id", sa.BigInteger, primary_key=True),
    sa.Column("symbol", sa.String(32), primary_key=True),
    sa.Column("holding", sa.Boolean, nullable=False, server_default=sa.false()),  # 📌 đang giữ (theo dõi Spot)
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

# 💼 Danh mục Spot: mỗi coin người dùng đang giữ (số lượng, giá vốn TB, vốn dự kiến cho DCA)
portfolio = sa.Table(
    "portfolio", meta,
    sa.Column("chat_id", sa.BigInteger, primary_key=True),
    sa.Column("symbol", sa.String(32), primary_key=True),  # mã Binance Futures dùng để lấy dữ liệu (vd 1000PEPEUSDT)
    sa.Column("qty", sa.Float, nullable=False, server_default="0"),  # số coin thật (đã quy đổi hệ số 1000)
    sa.Column("avg_price", sa.Float, nullable=False, server_default="0"),  # giá vốn TB / 1 coin (USDT)
    sa.Column("invested", sa.Float, nullable=False, server_default="0"),  # tổng tiền đã mua (USDT)
    sa.Column("realized", sa.Float, nullable=False, server_default="0"),  # lời/lỗ đã chốt (USDT)
    sa.Column("budget", sa.Float, nullable=False, server_default="0"),  # tổng vốn dự kiến cho DCA (USDT)
    sa.Column("plan", sa.Text),  # kế hoạch DCA đã chốt (JSON: các mốc giá, số tiền, trạng thái)
    sa.Column("exchange", sa.String(16), nullable=False, server_default="Binance"),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

# Lịch sử mua/bán trong danh mục (giữ sàn + đơn vị tiền để sau này hỗ trợ sàn Việt / VND)
portfolio_tx = sa.Table(
    "portfolio_tx", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("chat_id", sa.BigInteger, nullable=False, index=True),
    sa.Column("symbol", sa.String(32), nullable=False),
    sa.Column("side", sa.String(4), nullable=False),  # buy | sell
    sa.Column("qty", sa.Float, nullable=False),
    sa.Column("price", sa.Float, nullable=False),  # USDT / 1 coin
    sa.Column("amount", sa.Float, nullable=False),  # USDT
    sa.Column("currency", sa.String(8), nullable=False, server_default="USDT"),  # đơn vị người dùng đã nhập
    sa.Column("exchange", sa.String(16), nullable=False, server_default="Binance"),
    sa.Column("note", sa.String(64)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

kv = sa.Table(
    "kv", meta,
    sa.Column("key", sa.String(128), primary_key=True),
    sa.Column("value", sa.Text, nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)

# Nhật ký các lần tin tức chặn tín hiệu -> sau 1-2 tháng đối chiếu xem chặn đúng hay sai
news_blocks = sa.Table(
    "news_blocks", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("symbol", sa.String(32), nullable=False),
    sa.Column("side", sa.SmallInteger, nullable=False),
    sa.Column("price", sa.Float, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)


def _url(raw: str) -> tuple[str, dict]:
    """Chuẩn hóa URL Postgres của Neon/Render sang driver asyncpg."""
    if raw.startswith(("postgres://", "postgresql://")):
        base = raw.split("?", 1)[0].replace("postgres://", "postgresql://", 1)
        return base.replace("postgresql://", "postgresql+asyncpg://", 1), {"ssl": "require" in raw or "neon" in raw}
    return raw, {}


_engine: AsyncEngine | None = None


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url, args = _url(settings.database_url)
        _engine = create_async_engine(url, connect_args=args, pool_pre_ping=True)
    return _engine


def _add_missing_columns(conn) -> None:
    """create_all không thêm cột vào bảng đã có -> tự ALTER TABLE cho các cột mới (giữ nguyên dữ liệu)."""
    insp = sa.inspect(conn)
    for table in meta.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in have:
                ddl = col.type.compile(dialect=conn.dialect)
                default = ""
                if col.server_default is not None:
                    arg = col.server_default.arg
                    arg = arg if isinstance(arg, str) else str(arg.compile(dialect=conn.dialect))
                    default = f" DEFAULT {arg}" if arg.replace(".", "", 1).isdigit() or arg.lower() in ("true", "false", "1", "0")                         else f" DEFAULT '{arg}'"
                null = " NOT NULL" if not col.nullable and default else ""
                conn.execute(sa.text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}{default}{null}"))


async def init() -> None:
    async with engine().begin() as conn:
        await conn.run_sync(meta.create_all)
        await conn.run_sync(_add_missing_columns)
    # v3.3: tin tức mặc định chỉ gửi vào topic 📰 của nhóm -> tắt tin tức ở chat riêng 1 lần cho người dùng cũ
    if not await kv_get("migr:news_dm_off"):
        async with engine().begin() as c:
            await c.execute(users.update().values(news_dm=False))
        await kv_set("migr:news_dm_off", "1")
    # v3.4: coin 📌 "đang giữ" cũ -> chuyển sang 💼 Danh mục Spot (chưa có số lượng, người dùng tự ghi lệnh mua)
    if not await kv_get("migr:holding_to_portfolio"):
        async with engine().begin() as c:
            rows = (await c.execute(sa.select(user_coins).where(user_coins.c.holding))).all()
            for r in rows:
                if not (await c.execute(sa.select(portfolio).where(portfolio.c.chat_id == r.chat_id,
                                                                   portfolio.c.symbol == r.symbol))).first():
                    await c.execute(portfolio.insert().values(chat_id=r.chat_id, symbol=r.symbol, created_at=now()))
        await kv_set("migr:holding_to_portfolio", "1")


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite trả datetime không có múi giờ -> gắn UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _encode(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return {"__dt": obj.isoformat()}
    raise TypeError(type(obj))


def _decode(d: dict) -> Any:
    return datetime.fromisoformat(d["__dt"]) if "__dt" in d else d


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=_encode, ensure_ascii=False)


def loads(text: str) -> Any:
    return json.loads(text, object_hook=_decode)


def _row(r) -> dict:
    d = dict(r._mapping)
    for k in ("created_at", "closed_at"):
        if k in d:
            d[k] = _aware(d[k])
    return d


# ---------------------------------------------------------------- users
async def upsert_user(chat_id: int, username: str | None, full_name: str | None = None) -> dict:
    async with engine().begin() as c:
        row = (await c.execute(sa.select(users).where(users.c.chat_id == chat_id))).first()
        if row is None:
            # người đã bị admin xóa quay lại -> luôn phải chờ admin duyệt
            was_deleted = (await c.execute(sa.select(kv.c.value).where(kv.c.key == f"deleted:{chat_id}"))).first()
            approved = ((not settings.private_mode) or chat_id in settings.admin_ids) and not (was_deleted and was_deleted.value)
            await c.execute(users.insert().values(chat_id=chat_id, username=username, full_name=full_name, mode="futures",
                                                  risk_pct=settings.default_risk_pct, subscribed=True,
                                                  banned=False, approved=approved, news_dm=False, created_at=now()))
            row = (await c.execute(sa.select(users).where(users.c.chat_id == chat_id))).first()
        elif (username and row.username != username) or (full_name and row.full_name != full_name):
            await c.execute(users.update().where(users.c.chat_id == chat_id)
                            .values(username=username or row.username, full_name=full_name or row.full_name))
            row = (await c.execute(sa.select(users).where(users.c.chat_id == chat_id))).first()
    return _row(row)


async def get_user(chat_id: int) -> dict | None:
    async with engine().connect() as c:
        row = (await c.execute(sa.select(users).where(users.c.chat_id == chat_id))).first()
    return _row(row) if row else None


async def update_user(chat_id: int, **values) -> None:
    async with engine().begin() as c:
        await c.execute(users.update().where(users.c.chat_id == chat_id).values(**values))


async def subscribers() -> list[dict]:
    async with engine().connect() as c:
        rows = (await c.execute(sa.select(users).where(users.c.subscribed, ~users.c.banned, users.c.approved,
                                                      ~users.c.admin_muted))).all()
    return [_row(r) for r in rows]


async def all_users() -> list[dict]:
    async with engine().connect() as c:
        return [_row(r) for r in (await c.execute(sa.select(users).order_by(users.c.created_at))).all()]


# ---------------------------------------------------------------- watchlist
async def get_watchlist() -> list[str]:
    async with engine().connect() as c:
        return [r.symbol for r in (await c.execute(sa.select(watchlist.c.symbol).order_by(watchlist.c.created_at))).all()]


async def add_watch(symbol: str, added_by: int) -> bool:
    async with engine().begin() as c:
        if (await c.execute(sa.select(watchlist).where(watchlist.c.symbol == symbol))).first():
            return False
        await c.execute(watchlist.insert().values(symbol=symbol, added_by=added_by, created_at=now()))
    return True


async def remove_watch(symbol: str) -> bool:
    async with engine().begin() as c:
        return (await c.execute(watchlist.delete().where(watchlist.c.symbol == symbol))).rowcount > 0


# ---------------------------------------------------------------- signals
async def insert_signal(**values) -> int:
    values.setdefault("created_at", now())
    async with engine().begin() as c:
        res = await c.execute(signals.insert().values(**values))
        return int(res.inserted_primary_key[0])


async def update_signal(signal_id: int, **values) -> None:
    async with engine().begin() as c:
        await c.execute(signals.update().where(signals.c.id == signal_id).values(**values))


async def open_signals() -> list[dict]:
    async with engine().connect() as c:
        rows = (await c.execute(sa.select(signals).where(signals.c.status == "ACTIVE"))).all()
    return [_row(r) for r in rows]


async def signals_since(since: datetime) -> list[dict]:
    async with engine().connect() as c:
        rows = (await c.execute(sa.select(signals).where(signals.c.created_at >= since)
                                .order_by(signals.c.created_at.desc()))).all()
    return [_row(r) for r in rows]


async def recent_signals(limit: int = 10) -> list[dict]:
    async with engine().connect() as c:
        rows = (await c.execute(sa.select(signals).order_by(signals.c.created_at.desc()).limit(limit))).all()
    return [_row(r) for r in rows]


async def last_signal_time(symbol: str) -> datetime | None:
    async with engine().connect() as c:
        v = (await c.execute(sa.select(sa.func.max(signals.c.closed_at)).where(signals.c.symbol == symbol))).scalar()
        opened = (await c.execute(sa.select(sa.func.max(signals.c.created_at)).where(signals.c.symbol == symbol))).scalar()
    return max((x for x in (_aware(v), _aware(opened)) if x), default=None)


async def closed_signals(days: int | None = None) -> list[dict]:
    q = sa.select(signals).where(signals.c.status == "CLOSED")
    if days:
        q = q.where(signals.c.closed_at >= now() - timedelta(days=days))
    async with engine().connect() as c:
        return [_row(r) for r in (await c.execute(q)).all()]


async def add_message(signal_id: int, chat_id: int, message_id: int) -> None:
    async with engine().begin() as c:
        await c.execute(signal_messages.insert().values(signal_id=signal_id, chat_id=chat_id, message_id=message_id))


async def messages_for(signal_id: int) -> list[dict]:
    async with engine().connect() as c:
        rows = (await c.execute(sa.select(signal_messages).where(signal_messages.c.signal_id == signal_id))).all()
    return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------- kv / nhật ký
async def kv_get(key: str) -> str | None:
    async with engine().connect() as c:
        row = (await c.execute(sa.select(kv.c.value).where(kv.c.key == key))).first()
    return row.value if row else None


async def kv_set(key: str, value: str) -> None:
    async with engine().begin() as c:
        if (await c.execute(sa.select(kv.c.key).where(kv.c.key == key))).first():
            await c.execute(kv.update().where(kv.c.key == key).values(value=value, updated_at=now()))
        else:
            await c.execute(kv.insert().values(key=key, value=value, updated_at=now()))


async def log_news_block(symbol: str, side: int, price: float, reason: str) -> None:
    async with engine().begin() as c:
        await c.execute(news_blocks.insert().values(symbol=symbol, side=side, price=price, reason=reason[:500],
                                                    created_at=now()))


# ---------------------------------------------------------------- coin tự chọn
async def user_coins_of(chat_id: int) -> list[dict]:
    async with engine().connect() as c:
        rows = (await c.execute(sa.select(user_coins).where(user_coins.c.chat_id == chat_id)
                                .order_by(user_coins.c.created_at))).all()
    return [dict(r._mapping) for r in rows]


async def all_user_coins() -> list[dict]:
    """Coin tự chọn đang dùng của mọi người dùng đã duyệt, không bị chặn:
    chế độ Futures -> 🪙 Coin theo dõi; chế độ Spot -> coin trong 💼 Danh mục."""
    fut = (sa.select(user_coins.c.chat_id, user_coins.c.symbol)
           .join(users, users.c.chat_id == user_coins.c.chat_id)
           .where(users.c.approved, ~users.c.banned, users.c.mode == "futures"))
    spot = (sa.select(portfolio.c.chat_id, portfolio.c.symbol)
            .join(users, users.c.chat_id == portfolio.c.chat_id)
            .where(users.c.approved, ~users.c.banned, users.c.mode == "spot"))
    async with engine().connect() as c:
        return [dict(r._mapping) for q in (fut, spot) for r in (await c.execute(q)).all()]


async def add_user_coin(chat_id: int, symbol: str) -> bool:
    async with engine().begin() as c:
        if (await c.execute(sa.select(user_coins).where(user_coins.c.chat_id == chat_id,
                                                        user_coins.c.symbol == symbol))).first():
            return False
        await c.execute(user_coins.insert().values(chat_id=chat_id, symbol=symbol, holding=False, created_at=now()))
    return True


async def remove_user_coin(chat_id: int, symbol: str) -> None:
    async with engine().begin() as c:
        await c.execute(user_coins.delete().where(user_coins.c.chat_id == chat_id, user_coins.c.symbol == symbol))


async def toggle_holding(chat_id: int, symbol: str) -> None:
    async with engine().begin() as c:
        await c.execute(user_coins.update().where(user_coins.c.chat_id == chat_id, user_coins.c.symbol == symbol)
                        .values(holding=~user_coins.c.holding))


async def messages_since(chat_id: int, since: datetime) -> list[dict]:
    """Tín hiệu đã gửi cho 1 người từ mốc `since` (để giới hạn số tín hiệu/ngày riêng từng người)."""
    q = (sa.select(signals.c.id, signals.c.style, signals.c.source)
         .join(signal_messages, signal_messages.c.signal_id == signals.c.id)
         .where(signal_messages.c.chat_id == chat_id, signals.c.created_at >= since))
    async with engine().connect() as c:
        return [dict(r._mapping) for r in (await c.execute(q)).all()]


async def get_signal(signal_id: int) -> dict | None:
    async with engine().connect() as c:
        row = (await c.execute(sa.select(signals).where(signals.c.id == signal_id))).first()
    return _row(row) if row else None


async def kv_incr(key: str) -> int:
    n = int(await kv_get(key) or 0) + 1
    await kv_set(key, str(n))
    return n


async def signal_by_message(chat_id: int, message_id: int) -> dict | None:
    """Tín hiệu ứng với tin nhắn bot đã gửi (để trả lời khi người dùng reply vào tín hiệu)."""
    q = (sa.select(signals).join(signal_messages, signal_messages.c.signal_id == signals.c.id)
         .where(signal_messages.c.chat_id == chat_id, signal_messages.c.message_id == message_id))
    async with engine().connect() as c:
        row = (await c.execute(q)).first()
    return _row(row) if row else None


async def kv_decr(key: str) -> None:
    n = int(await kv_get(key) or 0)
    if n > 0:
        await kv_set(key, str(n - 1))


# ---------------------------------------------------------------- 💼 danh mục Spot
async def portfolio_of(chat_id: int) -> list[dict]:
    async with engine().connect() as c:
        rows = (await c.execute(sa.select(portfolio).where(portfolio.c.chat_id == chat_id)
                                .order_by(portfolio.c.created_at))).all()
    return [_row(r) for r in rows]


async def position(chat_id: int, symbol: str) -> dict | None:
    async with engine().connect() as c:
        row = (await c.execute(sa.select(portfolio).where(portfolio.c.chat_id == chat_id,
                                                          portfolio.c.symbol == symbol))).first()
    return _row(row) if row else None


async def all_positions() -> list[dict]:
    """Coin trong danh mục của mọi người dùng đã duyệt, không bị chặn (để theo dõi, cảnh báo DCA)."""
    q = (sa.select(portfolio).join(users, users.c.chat_id == portfolio.c.chat_id)
         .where(users.c.approved, ~users.c.banned))
    async with engine().connect() as c:
        return [_row(r) for r in (await c.execute(q)).all()]


async def add_position(chat_id: int, symbol: str) -> bool:
    async with engine().begin() as c:
        if (await c.execute(sa.select(portfolio).where(portfolio.c.chat_id == chat_id,
                                                       portfolio.c.symbol == symbol))).first():
            return False
        await c.execute(portfolio.insert().values(chat_id=chat_id, symbol=symbol, created_at=now()))
    return True


async def remove_position(chat_id: int, symbol: str) -> None:
    async with engine().begin() as c:
        await c.execute(portfolio.delete().where(portfolio.c.chat_id == chat_id, portfolio.c.symbol == symbol))


async def update_position(chat_id: int, symbol: str, **values) -> None:
    async with engine().begin() as c:
        await c.execute(portfolio.update().where(portfolio.c.chat_id == chat_id, portfolio.c.symbol == symbol)
                        .values(**values))


def apply_trade(pos: dict, side: str, qty: float, price: float) -> dict:
    """Cập nhật số lượng / giá vốn TB / lời lỗ đã chốt sau 1 lệnh mua hoặc bán (giá theo USDT / 1 coin)."""
    q0, avg = pos.get("qty") or 0.0, pos.get("avg_price") or 0.0
    out = {"qty": q0, "avg_price": avg, "invested": pos.get("invested") or 0.0, "realized": pos.get("realized") or 0.0}
    if side == "buy":
        out["qty"] = q0 + qty
        out["avg_price"] = (q0 * avg + qty * price) / out["qty"] if out["qty"] > 0 else 0.0
        out["invested"] += qty * price
    else:
        qty = min(qty, q0)
        out["qty"] = q0 - qty
        out["realized"] += qty * (price - avg)
        if out["qty"] <= 1e-12:
            out["qty"], out["avg_price"] = 0.0, 0.0
    return out


async def record_trade(chat_id: int, symbol: str, side: str, qty: float, price: float, *,
                       currency: str = "USDT", note: str | None = None) -> dict:
    """Ghi 1 lệnh mua/bán vào lịch sử và cập nhật danh mục. Trả về vị thế mới."""
    pos = await position(chat_id, symbol)
    if pos is None:
        await add_position(chat_id, symbol)
        pos = await position(chat_id, symbol)
    if side == "sell":
        qty = min(qty, pos["qty"])
    new = apply_trade(pos, side, qty, price)
    async with engine().begin() as c:
        await c.execute(portfolio_tx.insert().values(chat_id=chat_id, symbol=symbol, side=side, qty=qty, price=price,
                                                     amount=qty * price, currency=currency, exchange=pos["exchange"],
                                                     note=note, created_at=now()))
        await c.execute(portfolio.update().where(portfolio.c.chat_id == chat_id, portfolio.c.symbol == symbol)
                        .values(**new))
    return {**pos, **new}


async def trades_of(chat_id: int, symbol: str, limit: int = 15) -> list[dict]:
    async with engine().connect() as c:
        rows = (await c.execute(sa.select(portfolio_tx).where(portfolio_tx.c.chat_id == chat_id,
                                                              portfolio_tx.c.symbol == symbol)
                                .order_by(portfolio_tx.c.id.desc()).limit(limit))).all()
    return [_row(r) for r in rows]


async def user_signals(chat_id: int, days: int = 30) -> list[dict]:
    """Tín hiệu đã gửi cho 1 người trong `days` ngày (mới nhất trước), kèm message_id tin tín hiệu."""
    since = now() - timedelta(days=days)
    q = (sa.select(signals, signal_messages.c.message_id)
         .join(signal_messages, signal_messages.c.signal_id == signals.c.id)
         .where(signal_messages.c.chat_id == chat_id, signals.c.created_at >= since)
         .order_by(signals.c.id.desc()))
    async with engine().connect() as c:
        return [_row(r) for r in (await c.execute(q)).all()]


async def delete_user(chat_id: int) -> None:
    """Admin xóa người dùng: xóa cài đặt, coin theo dõi, danh mục + lịch sử danh mục. Lịch sử tín hiệu đã gửi giữ lại
    để thống kê. Đánh dấu 'đã xóa' để lần sau quay lại phải chờ admin duyệt (kể cả thành viên nhóm)."""
    async with engine().begin() as c:
        for table in (user_coins, portfolio, portfolio_tx):
            await c.execute(table.delete().where(table.c.chat_id == chat_id))
        await c.execute(users.delete().where(users.c.chat_id == chat_id))
    await kv_set(f"deleted:{chat_id}", "1")
    await kv_set(f"pending:{chat_id}", "")
