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
    sa.Column("subscribed", sa.Boolean, nullable=False, server_default=sa.true()),
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


async def init() -> None:
    async with engine().begin() as conn:
        await conn.run_sync(meta.create_all)


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
async def upsert_user(chat_id: int, username: str | None) -> dict:
    async with engine().begin() as c:
        row = (await c.execute(sa.select(users).where(users.c.chat_id == chat_id))).first()
        if row is None:
            await c.execute(users.insert().values(chat_id=chat_id, username=username, mode="futures",
                                                  risk_pct=settings.default_risk_pct, subscribed=True,
                                                  banned=False, created_at=now()))
            row = (await c.execute(sa.select(users).where(users.c.chat_id == chat_id))).first()
        elif username and row.username != username:
            await c.execute(users.update().where(users.c.chat_id == chat_id).values(username=username))
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
        rows = (await c.execute(sa.select(users).where(users.c.subscribed, ~users.c.banned))).all()
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
