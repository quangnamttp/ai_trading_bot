"""💼 Danh mục Spot trong chat riêng: xem danh mục, ghi mua/bán, đặt vốn DCA, nhắc khi giá chạm vùng DCA."""
from __future__ import annotations

import asyncio
import logging
from html import escape

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from app import portfolio as pf, reports, storage
from app.bot import extra, texts
from app.config import settings
from app.data import binance

log = logging.getLogger(__name__)

NUM = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
STATUS = {"pending": "⏳ chờ", "done": "✅ đã mua", "skipped": "⏭ bỏ qua"}
B = InlineKeyboardButton


def _pct(x: float | None) -> str:
    return "" if x is None else f"{'🟢' if x >= 0 else '🔴'} {x:+.1%}"


async def list_view(user: dict) -> tuple[str, InlineKeyboardMarkup]:
    cur = user.get("currency", "USDT")
    fx = await pf.rate(cur)
    pos = await storage.portfolio_of(user["chat_id"])
    px = await pf.prices([p["symbol"] for p in pos]) if pos else {}
    lines = [f"💼 <b>Danh mục Spot của tôi</b> · đơn vị {'VNĐ' if cur == 'VND' and fx else 'USDT'}", ""]
    tot_val = tot_cost = 0.0
    for p in pos:
        price = px.get(p["symbol"], {}).get("price")
        v = pf.valuation(p, price)
        base = escape(pf.base_of(p["symbol"]))
        if v["qty"] > 0:
            tot_val += v["value"]
            tot_cost += v["cost"]
            lines.append(f"• <b>{base}</b>: {v['qty']:.6g} · vốn {texts.price(v['avg'])} → {texts.price(price) if price else '?'} "
                         f"{_pct(v['pnl_pct'])} ({pf.money(v['pnl'], cur, fx, sign=True)})")
        else:
            lines.append(f"• <b>{base}</b>: chưa ghi lệnh mua · giá {texts.price(price) if price else '?'}")
    if not pos:
        lines.append("Chưa có coin nào. Bấm ➕ Thêm coin, sau đó bấm tên coin → ➕ Mua để ghi số tiền đã mua.")
    elif tot_cost > 0:
        lines += ["", f"Tổng giá trị: <b>{pf.money(tot_val, cur, fx)}</b> · vốn {pf.money(tot_cost, cur, fx)}",
                  f"Lời/lỗ: <b>{pf.money(tot_val - tot_cost, cur, fx, sign=True)}</b> ({(tot_val / tot_cost - 1):+.1%})"]
    if cur == "VND" and not fx:
        lines.append("<i>Chưa lấy được tỉ giá USDT/VND — tạm hiển thị USDT.</i>")
    mode = user.get("coin_mode", "top")
    lines += ["", f"Tín hiệu Spot nhận từ: <b>{ {'top': 'Top 20', 'mine': 'chỉ coin trong danh mục', 'both': 'Top 20 + danh mục'}[mode] }</b>",
              extra.ind_line(user), "<i>Bấm tên coin để ghi mua/bán, đặt vốn DCA, xem lịch sử.</i>"]
    btns = [B(pf.base_of(p["symbol"]), callback_data=f"pf:v:{p['symbol']}") for p in pos]
    rows = [btns[i:i + 3] for i in range(0, len(btns), 3)]
    rows.append([B("➕ Thêm coin", callback_data="pf:add"),
                 B("💱 Đổi sang " + ("USDT" if cur == "VND" else "VNĐ"), callback_data="pf:cur")])
    rows += extra.ind_rows(user)
    if pos:
        rows.append([B(("✅ " if mode == k else "") + t, callback_data=f"cmode:{k}")
                     for k, t in (("top", "Top 20"), ("mine", "Chỉ danh mục"), ("both", "Cả hai"))])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def coin_view(user: dict, symbol: str) -> tuple[str, InlineKeyboardMarkup]:
    cur = user.get("currency", "USDT")
    fx = await pf.rate(cur)
    p = await storage.position(user["chat_id"], symbol)
    if not p:
        return "Coin này không còn trong danh mục.", InlineKeyboardMarkup([[B("⬅️ Danh mục", callback_data="pf:list")]])
    info = (await pf.prices([symbol])).get(symbol, {})
    price = info.get("price")
    v = pf.valuation(p, price)
    base = escape(pf.base_of(symbol))
    lines = [f"💼 <b>{base}</b> · giá {texts.price(price) if price else '?'} USDT"
             + (f" (24h {info['chg24']:+.1%})" if info else "")]
    if v["qty"] > 0:
        lines += [f"Đang giữ: <b>{v['qty']:.6g} {base}</b> · giá vốn TB <b>{texts.price(v['avg'])}</b>",
                  f"Giá trị {pf.money(v['value'], cur, fx)} · lời/lỗ <b>{pf.money(v['pnl'], cur, fx, sign=True)}</b> "
                  f"{_pct(v['pnl_pct'])}"]
    else:
        lines.append("Chưa ghi lệnh mua nào — bấm ➕ Mua sau khi mua trên sàn.")
    if v["realized"]:
        lines.append(f"Lời/lỗ đã chốt: {pf.money(v['realized'], cur, fx, sign=True)}")
    plan = pf.plan_of(p)
    if plan:
        lines += ["", f"🎯 <b>Kế hoạch DCA</b> (vốn {pf.money(plan['budget'], cur, fx)} · còn "
                      f"{pf.money(pf.remaining_budget(p), cur, fx)}):"]
        for i, lv in enumerate(plan["levels"]):
            dist = f" ({lv['price'] / price - 1:+.1%})" if price and lv["status"] == "pending" else ""
            lines.append(f"{NUM[i]} {texts.price(lv['price'])} — {pf.money(lv['amount'], cur, fx)} · "
                         f"{STATUS[lv['status']]}{dist}\n     <i>{escape(lv['name'])}</i>")
        lines.append(f"⛔ Dừng DCA / xem lại nếu nến ngày đóng dưới <b>{texts.price(plan['stop'])}</b>")
        lines.append("<i>Bot nhắc khi giá chạm mốc.</i>")
    else:
        lines += ["", "🎯 Chưa có kế hoạch DCA — bấm <b>Đặt vốn DCA</b>, nhập số tiền dự kiến mua thêm, bot chia vào "
                      "các vùng hỗ trợ và nhắc khi giá chạm."]
    rows = [[B("➕ Mua / DCA", callback_data=f"pf:buy:{symbol}"), B("➖ Bán", callback_data=f"pf:sell:{symbol}")],
            [B("🎯 Đặt vốn DCA", callback_data=f"pf:bud:{symbol}")]
            + ([B("🔄 Tính lại mốc", callback_data=f"pf:re:{symbol}")] if plan else []),
            [B("📜 Lịch sử", callback_data=f"pf:hist:{symbol}"), B("🗑 Xóa coin", callback_data=f"pf:del:{symbol}")],
            [B("⬅️ Danh mục", callback_data="pf:list")]]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _show(update: Update, text: str, markup: InlineKeyboardMarkup, *, edit: bool) -> None:
    q = update.callback_query
    if edit and q:
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True)
            return
        except BadRequest:
            pass
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                              disable_web_page_preview=True)


async def show_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: dict, *, edit: bool = False) -> None:
    await _show(update, *await list_view(user), edit=edit)


async def show_coin(update: Update, user: dict, symbol: str, *, edit: bool = False) -> None:
    await _show(update, *await coin_view(user, symbol), edit=edit)


PROMPTS = {
    "add": "✍️ Gõ tên coin muốn thêm vào danh mục (nhiều coin cách nhau bằng dấu cách, vd: <code>SOL PEPE LINK</code>):",
    "buy": ("✍️ Gõ <b>số tiền đã mua</b>{unit}, thêm giá mua nếu khác giá hiện tại.\n"
            "Ví dụ: <code>{ex1}</code> (giá hiện tại) · <code>{ex2}</code>"),
    "sell": ("✍️ Gõ <b>số coin đã bán</b> hoặc phần trăm, thêm giá bán nếu khác giá hiện tại.\n"
             "Ví dụ: <code>0.5</code> · <code>50%</code> · <code>hết</code> · <code>0.5 {px}</code>"),
    "bud": ("✍️ Gõ <b>tổng số tiền dự kiến DCA thêm</b>{unit} cho coin này (gõ <code>0</code> để bỏ kế hoạch).\n"
            "Ví dụ: <code>{ex1}</code>"),
    "dca": "✍️ Gõ số tiền thực tế đã mua{unit} (bot ghi theo giá hiện tại):",
}


async def _prompt(q, op: str, user: dict, symbol: str | None) -> None:
    cur = user.get("currency", "USDT")
    unit = " (VNĐ)" if cur == "VND" else " (USDT)"
    ex1, ex2 = ("2tr", "2tr 2.500.000") if cur == "VND" else ("100", "100 95.5")
    px = ""
    if symbol:
        p = (await pf.prices([symbol])).get(symbol)
        px = texts.price(p["price"]) if p else "1.23"
    await q.message.reply_text(PROMPTS[op].format(unit=unit, ex1=ex1, ex2=ex2, px=px), parse_mode=ParseMode.HTML)


async def on_pf(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    user = await storage.get_user(q.from_user.id)
    if not user or not user.get("approved") or user.get("banned"):
        await q.answer()
        return
    _, op, *rest = q.data.split(":")
    sym = rest[0] if rest else None
    if op == "list":
        await q.answer()
        await show_list(update, ctx, user, edit=True)
    elif op == "cur":
        cur = "USDT" if user.get("currency", "USDT") == "VND" else "VND"
        await storage.update_user(user["chat_id"], currency=cur)
        await q.answer(f"Đơn vị hiển thị: {'VNĐ' if cur == 'VND' else 'USDT'}")
        await show_list(update, ctx, await storage.get_user(user["chat_id"]), edit=True)
    elif op == "v":
        await q.answer()
        await show_coin(update, user, sym, edit=True)
    elif op in ("add", "buy", "sell", "bud"):
        ctx.user_data["await_pf"] = {"op": op, "sym": sym}
        await q.answer()
        await _prompt(q, op, user, sym)
    elif op == "re":
        plan = await pf.replan(user["chat_id"], sym)
        await q.answer("Đã tính lại các mốc" if plan else "Không còn vốn DCA để chia")
        await show_coin(update, user, sym, edit=True)
    elif op == "hist":
        await q.answer()
        cur = user.get("currency", "USDT")
        fx = await pf.rate(cur)
        rows = await storage.trades_of(user["chat_id"], sym)
        lines = [f"📜 <b>Lịch sử {escape(pf.base_of(sym))}</b> (15 lệnh gần nhất)"]
        lines += [f"{'🟢 Mua' if t['side'] == 'buy' else '🔴 Bán'} {t['qty']:.6g} @ {texts.price(t['price'])} = "
                  f"{pf.money(t['amount'], cur, fx)} · {texts.vn_time(t['created_at'])}"
                  + (f" · {escape(t['note'])}" if t.get("note") else "") for t in rows] or ["Chưa có lệnh nào."]
        await q.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    elif op == "del":
        await q.answer()
        await q.message.reply_text(f"Xóa {escape(pf.base_of(sym))} khỏi danh mục? Lịch sử mua/bán vẫn được giữ.",
                                   reply_markup=InlineKeyboardMarkup([[B("🗑 Xóa", callback_data=f"pf:delok:{sym}"),
                                                                       B("Không", callback_data=f"pf:v:{sym}")]]))
    elif op == "delok":
        await storage.remove_position(user["chat_id"], sym)
        await q.answer("Đã xóa")
        await show_list(update, ctx, user, edit=True)
    else:
        await q.answer()


async def _current_price(symbol: str) -> float | None:
    p = (await pf.prices([symbol])).get(symbol)
    return p["price"] if p else None


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: dict, text: str) -> bool:
    """Xử lý số liệu người dùng gõ sau khi bấm nút danh mục. Trả True nếu đã xử lý."""
    st = ctx.user_data.pop("await_pf", None)
    if not st:
        return False
    msg = update.effective_message
    op, sym = st["op"], st.get("sym")
    cur = user.get("currency", "USDT")
    fx = await pf.rate(cur)
    if cur == "VND" and not fx:
        cur, fx = "USDT", 1.0
    if op == "add":
        await add_coins(update, user, text)
        return True
    parts = text.replace("@", " ").split()
    px_now = await _current_price(sym)
    if op in ("buy", "dca", "bud"):
        amount = pf.parse_number(parts[0], cur) if parts else None
        if amount is None or amount < 0 or (op != "bud" and amount == 0):
            await msg.reply_text("❌ Không đọc được số tiền. Bấm lại nút và gõ số, vd 100 hoặc 2tr.")
            return True
        usdt = amount / fx
        if op == "bud":
            plan = await pf.set_budget(user["chat_id"], sym, usdt)
            await msg.reply_text("✅ Đã bỏ kế hoạch DCA." if not plan else
                                 f"✅ Đã chia {pf.money(usdt, cur, fx)} vào {len(plan['levels'])} mốc DCA.")
        else:
            price = pf.parse_number(parts[1], cur) / fx if len(parts) > 1 and op == "buy" and pf.parse_number(parts[1], cur) else px_now
            if not price:
                await msg.reply_text("❌ Chưa lấy được giá, gõ kèm giá mua, vd 100 95.5.")
                return True
            await pf.buy(user["chat_id"], sym, usdt, price, currency=cur,
                         note=f"DCA mốc {st['i'] + 1}" if op == "dca" else None)
            note = ""
            if op == "dca":
                await pf.mark_level(user["chat_id"], sym, st["i"], "done")
            else:
                lv = await pf.match_level(user["chat_id"], sym, price)
                if lv is not None:
                    note = f" Đã đánh dấu ✅ mốc DCA {lv + 1}."
            await msg.reply_text(f"✅ Đã ghi mua {pf.money(usdt, cur, fx)} {escape(pf.base_of(sym))} giá {texts.price(price)}.{note}")
    elif op == "sell":
        p = await storage.position(user["chat_id"], sym)
        held = p["qty"] if p else 0.0
        raw = parts[0].lower() if parts else ""
        if raw in ("hết", "het", "tất", "all", "100%"):
            qty = held
        elif raw.endswith("%") and pf.parse_number(raw[:-1]) is not None:
            qty = held * pf.parse_number(raw[:-1]) / 100
        else:
            qty = pf.parse_number(raw) if raw else None
        price = pf.parse_number(parts[1], cur) / fx if len(parts) > 1 and pf.parse_number(parts[1], cur) else px_now
        if not qty or qty <= 0 or not price:
            await msg.reply_text("❌ Không đọc được số coin. Bấm lại ➖ Bán và gõ vd 0.5 hoặc 50%.")
            return True
        if held <= 0:
            await msg.reply_text("❌ Danh mục chưa có số lượng coin này để bán.")
            return True
        new = await pf.sell(user["chat_id"], sym, min(qty, held), price, currency=cur)
        await msg.reply_text(f"✅ Đã ghi bán {min(qty, held):.6g} {escape(pf.base_of(sym))} giá {texts.price(price)} · "
                             f"lời/lỗ đã chốt tổng {pf.money(new['realized'], cur, fx, sign=True)}.")
    await show_coin(update, await storage.get_user(user["chat_id"]), sym)
    return True


async def add_coins(update: Update, user: dict, raw: str) -> None:
    from app.bot.handlers import normalize_symbol
    have = await storage.portfolio_of(user["chat_id"])
    perps = await binance.perpetual_symbols()
    added, bad = [], []
    for token in raw.replace(",", " ").split():
        sym = normalize_symbol(token)
        sym = sym if sym in perps else f"1000{sym}" if f"1000{sym}" in perps else None
        if not sym:
            bad.append(token.upper())
        elif len(have) + len(added) >= settings.max_user_coins:
            bad.append(f"{token.upper()} (đã đủ {settings.max_user_coins} coin)")
        elif await storage.add_position(user["chat_id"], sym):
            added.append(pf.base_of(sym))
    msg = (["✅ Đã thêm: " + ", ".join(added)] if added else []) + \
          (["❌ Không thêm được (không có trên Binance?): " + ", ".join(bad)] if bad else [])
    await update.effective_message.reply_text("\n".join(msg) or "Không có gì thay đổi.")
    await show_list(update, None, await storage.get_user(user["chat_id"]))


# ---------------------------------------------------------------- nhắc DCA
async def on_dca(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    user = await storage.get_user(q.from_user.id)
    if not user or not user.get("approved") or user.get("banned"):
        await q.answer()
        return
    _, op, sym, i = q.data.split(":")
    i = int(i)
    p = await storage.position(user["chat_id"], sym)
    plan = pf.plan_of(p) if p else None
    if not plan or i >= len(plan["levels"]) or plan["levels"][i]["status"] != "pending":
        await q.answer("Mốc này đã xử lý rồi")
        return
    lv = plan["levels"][i]
    if op == "ok":
        price = await _current_price(sym)
        if not price:
            await q.answer("Chưa lấy được giá, thử lại sau")
            return
        await pf.buy(user["chat_id"], sym, lv["amount"], price, note=f"DCA mốc {i + 1}")
        await pf.mark_level(user["chat_id"], sym, i, "done")
        await q.answer("Đã ghi vào danh mục ✅")
        await q.edit_message_reply_markup(None)
        await show_coin(update, user, sym)
    elif op == "sk":
        await pf.mark_level(user["chat_id"], sym, i, "skipped")
        await q.answer("Đã bỏ qua mốc này")
        await q.edit_message_reply_markup(None)
    elif op == "ed":
        ctx.user_data["await_pf"] = {"op": "dca", "sym": sym, "i": i}
        await q.answer()
        await _prompt(q, "dca", user, sym)


async def dca_watch(bot: Bot) -> None:
    """Giá chạm mốc DCA -> nhắc kèm nút ✅ Đã mua / ✏️ Sửa số tiền / ⏭ Bỏ qua; nến ngày đóng dưới mức dừng -> cảnh báo."""
    from app.service import _send
    positions = [p for p in await storage.all_positions() if p.get("plan")]
    if not positions:
        return
    px = await pf.prices(list({p["symbol"] for p in positions}))
    daily: dict[str, float | None] = {}
    users = {u["chat_id"]: u for u in await storage.all_users()}
    for p in positions:
        sym, price = p["symbol"], px.get(p["symbol"], {}).get("price")
        if not price:
            continue
        if sym not in daily:
            try:
                d = await binance.klines(sym, "1d", 3)
                daily[sym] = float(d["close"].iloc[-1]) / pf.mult_of(sym)
            except Exception:  # noqa: BLE001
                daily[sym] = None
        u = users.get(p["chat_id"], {})
        cur = u.get("currency", "USDT")
        fx = await pf.rate(cur)
        plan = pf.plan_of(p)
        base = escape(pf.base_of(sym))
        for kind, i in pf.due_alerts(p, price, daily[sym]):
            if kind == "level":
                lv = plan["levels"][i]
                lv["alerted"] = True
                text = (f"🎯 <b>{base} chạm vùng DCA {i + 1}</b> ({texts.price(lv['price'])} · {escape(lv['name'])})\n"
                        f"Giá hiện tại {texts.price(price)} · kế hoạch mua <b>{pf.money(lv['amount'], cur, fx)}</b>.\n"
                        "Mua trên sàn xong thì bấm ✅ để bot cập nhật danh mục.")
                markup = InlineKeyboardMarkup([[B("✅ Đã mua", callback_data=f"dca:ok:{sym}:{i}"),
                                                B("✏️ Sửa số tiền", callback_data=f"dca:ed:{sym}:{i}"),
                                                B("⏭ Bỏ qua", callback_data=f"dca:sk:{sym}:{i}")]])
            else:
                plan["stop_alerted"] = True
                text = (f"⛔ <b>{base}</b>: nến ngày đóng dưới mức dừng DCA {texts.price(plan['stop'])}.\n"
                        "Vùng hỗ trợ đã thủng — tạm dừng mua thêm, xem lại kế hoạch (🔄 Tính lại mốc) hoặc cân nhắc giảm vị thế.")
                markup = InlineKeyboardMarkup([[B("💼 Xem coin", callback_data=f"pf:v:{sym}")]])
            await storage.update_position(p["chat_id"], sym, plan=storage.dumps(plan))
            try:
                await _send(bot, p["chat_id"], text, markup=markup, silent=reports.is_quiet())
            except TelegramError as exc:
                log.warning("Nhắc DCA %s lỗi: %s", p["chat_id"], exc)
            await asyncio.sleep(0.05)


def register(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(on_pf, pattern=r"^pf:"))
    app.add_handler(CallbackQueryHandler(on_dca, pattern=r"^dca:"))
