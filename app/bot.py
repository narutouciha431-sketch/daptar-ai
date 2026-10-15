"""Telegram-бот Дәптер AI (один бот на все магазины).

Покупатель: сканирует QR на кассе → бот показывает долг → «Растаймын» / «Жоқ».
После этого бот может присылать ему напоминания со ссылкой Kaspi.
Владелец: подключается по ссылке своего магазина и получает уведомления и вечерний отчёт.
"""
import html
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from . import texts as T
from .config import BOT_TOKEN, BOT_USERNAME
from .db import DEMO_EMAIL, customer_balance, get_shop, session
from .live import hub
from .reports import daily_report, report_text

log = logging.getLogger("daptar.bot")
app: Application | None = None


def deep_link(payload: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={payload}"


def enabled() -> bool:
    return app is not None


def _lang(value: str | None) -> str:
    return value if value in ("kk", "ru") else "kk"


# ---------- согласие на долг ----------
def consent_message(sale_id: int) -> tuple[str, InlineKeyboardMarkup, str, int] | None:
    with session() as c:
        s = c.execute(
            "SELECT s.*, cu.name AS cname, cu.language AS lang FROM sale s JOIN customer cu ON cu.id = s.customer_id WHERE s.id = ?",
            (sale_id,),
        ).fetchone()
        if not s:
            return None
        items = [dict(r) for r in c.execute("SELECT name, qty FROM sale_item WHERE sale_id = ?", (sale_id,))]
        shop = get_shop(c, s["shop_id"])
    lang = _lang(s["lang"])
    # Имена и товары экранируем: «&» или «<» в названии иначе ломают сообщение Telegram
    text = T.CONSENT[lang].format(
        name=html.escape(s["cname"]), shop=html.escape(shop["name"]), items=html.escape(T.items_line(items)),
        debt=T.money(s["total"] - s["paid_now"]), due=T.date_kk_ru(s["due_date"]),
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(T.BTN_YES[lang], callback_data=f"c:{s['consent_token']}:y"),
        InlineKeyboardButton(T.BTN_NO[lang], callback_data=f"c:{s['consent_token']}:n"),
    ]])
    return text, kb, lang, s["shop_id"]


def other_account(customer_id: int, chat_id: int) -> bool:
    """Покупатель уже привязан к другому Telegram — чужой человек не может подтверждать его долги."""
    with session() as c:
        row = c.execute("SELECT tg_chat_id FROM customer WHERE id = ?", (customer_id,)).fetchone()
    return bool(row and row["tg_chat_id"] and row["tg_chat_id"] != chat_id)


async def on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    payload = ctx.args[0] if ctx.args else ""
    chat_id = update.effective_chat.id

    # Владелец подключается по секретной ссылке своего магазина
    if payload.startswith("owner_"):
        with session() as c:
            shop = c.execute("SELECT shop.id, shop.name, user.email FROM shop JOIN user ON user.id = shop.user_id "
                             "WHERE owner_secret = ?", (payload[6:],)).fetchone()
            if shop and shop["email"] == DEMO_EMAIL:
                await update.message.reply_text("Демо-магазин общий для всех, поэтому Telegram к нему не подключается. "
                                                "Зарегистрируйте свой магазин и подключитесь из его «Настроек».")
                return
            if shop:
                # Один Telegram — один магазин: со старого магазина этот чат отвязываем
                c.execute("UPDATE shop SET owner_chat = NULL, owner_username = NULL WHERE owner_chat = ? AND id != ?", (chat_id, shop["id"]))
                c.execute("UPDATE shop SET owner_chat = ?, owner_username = ? WHERE id = ?",
                          (chat_id, update.effective_user.username if update.effective_user else None, shop["id"]))
        if shop:
            await update.message.reply_text(f"✅ «{shop['name']}» дүкенінің иесі ретінде қосылдыңыз. / "
                                            f"Вы подключены как владелец магазина «{shop['name']}».\n\nКоманда /report — отчёт за сегодня.")
            await hub.broadcast(shop["id"], {"type": "owner_linked"})
        else:
            await update.message.reply_text("Ссылка владельца неверна.")
        return

    # Покупатель открыл QR со своим долгом
    if payload.startswith("d_"):
        # Чат покупателя привязываем только после «Растаймын» — просто открыть QR мог и продавец, и сосед
        with session() as c:
            s = c.execute("SELECT id, status, customer_id, shop_id FROM sale WHERE consent_token = ?", (payload[2:],)).fetchone()
        if not s:
            await update.message.reply_text(T.UNKNOWN_LINK["kk"] + "\n" + T.UNKNOWN_LINK["ru"])
            return
        text, kb, lang, shop_id = consent_message(s["id"])
        if other_account(s["customer_id"], chat_id):
            await update.message.reply_text(T.OTHER_ACCOUNT)
            return
        if s["status"] != "pending":
            await update.message.reply_text(T.CONSENT_ALREADY[lang])
            return
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        await hub.broadcast(shop_id, {"type": "consent_opened", "sale_id": s["id"]})
        return

    await update.message.reply_text(T.WELCOME)


async def on_consent(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, token, answer = q.data.split(":")
    with session() as c:
        s = c.execute(
            "SELECT s.*, cu.name AS cname, cu.language AS lang FROM sale s JOIN customer cu ON cu.id = s.customer_id WHERE consent_token = ?",
            (token,),
        ).fetchone()
        if not s:
            await q.answer()
            return
        lang = _lang(s["lang"])
        if s["status"] != "pending":
            await q.answer(T.CONSENT_ALREADY[lang], show_alert=True)
            return
        if other_account(s["customer_id"], q.message.chat.id):
            await q.answer(T.OTHER_ACCOUNT, show_alert=True)
            return
        status = "confirmed" if answer == "y" else "rejected"
        c.execute("UPDATE sale SET status = ?, consent_at = ? WHERE id = ?",
                  (status, datetime.now().isoformat(sep=" ", timespec="seconds"), s["id"]))
        if status == "confirmed":
            c.execute("UPDATE customer SET tg_chat_id = ?, tg_username = ? WHERE id = ?",
                      (q.message.chat.id, q.from_user.username if q.from_user else None, s["customer_id"]))
    await q.answer()
    await q.edit_message_reply_markup(None)
    await q.message.reply_text(T.CONSENT_OK[lang] if status == "confirmed" else T.CONSENT_NO[lang])
    await hub.broadcast(s["shop_id"], {"type": "consent_changed", "sale_id": s["id"], "status": status, "customer": s["cname"]})
    debt = T.money(s["total"] - s["paid_now"])
    name = html.escape(s["cname"])
    await notify_owner(s["shop_id"], f"✅ {name} подтвердил(а) долг {debt}" if status == "confirmed"
                       else f"❌ {name} отклонил(а) долг {debt}. Проверьте запись.")


async def send_consent_request(sale_id: int) -> bool:
    """Если покупатель уже подключён к боту — отправляем запрос на подтверждение сразу."""
    if not enabled():
        return False
    with session() as c:
        row = c.execute("SELECT cu.tg_chat_id FROM sale s JOIN customer cu ON cu.id = s.customer_id WHERE s.id = ?", (sale_id,)).fetchone()
    if not row or not row["tg_chat_id"]:
        return False
    text, kb, _, _ = consent_message(sale_id)
    try:
        await app.bot.send_message(row["tg_chat_id"], text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return True
    except Exception as e:
        log.warning("consent send failed: %s", e)
        return False


# ---------- напоминания ----------
def reminder_text(customer_id: int) -> dict:
    with session() as c:
        cu = c.execute("SELECT * FROM customer WHERE id = ?", (customer_id,)).fetchone()
        if not cu:
            raise ValueError("Покупатель не найден")
        balance = customer_balance(c, customer_id)
        shop = get_shop(c, cu["shop_id"])
    lang = _lang(cu["language"])
    kaspi = shop["kaspi_link"].strip()
    pay = T.PAY_LINE[lang].format(kaspi=kaspi) if kaspi else ""
    text = T.REMINDER[lang].format(name=cu["name"], shop=shop["name"], debt=T.money(balance), pay=pay)
    return {"text": text, "lang": lang, "balance": balance, "kaspi": kaspi,
            "telegram": bool(cu["tg_chat_id"]) and enabled(), "phone": cu["phone"], "name": cu["name"]}


async def send_reminder(customer_id: int, text: str) -> bool:
    info = reminder_text(customer_id)
    if not info["telegram"]:
        return False
    with session() as c:
        chat = c.execute("SELECT tg_chat_id FROM customer WHERE id = ?", (customer_id,)).fetchone()["tg_chat_id"]
    lang = info["lang"]
    buttons = []
    if info["kaspi"].startswith("http"):
        buttons.append([InlineKeyboardButton(T.BTN_PAY[lang], url=info["kaspi"])])
    buttons.append([InlineKeyboardButton(T.BTN_PAID[lang], callback_data=f"p:{customer_id}")])
    # Текст мог отредактировать владелец — экранируем, чтобы символы < > не ломали разметку
    await app.bot.send_message(chat, html.escape(text), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
    return True


async def on_paid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    cid = int(q.data.split(":")[1])
    with session() as c:
        cu = c.execute("SELECT name, language, shop_id, tg_chat_id FROM customer WHERE id = ?", (cid,)).fetchone()
    await q.answer()
    if not cu or cu["tg_chat_id"] != q.message.chat.id:
        return
    await q.edit_message_reply_markup(None)
    await q.message.reply_text(T.PAID_THANKS[_lang(cu["language"])])
    await hub.broadcast(cu["shop_id"], {"type": "customer_says_paid", "customer_id": cid, "customer": cu["name"]})
    await notify_owner(cu["shop_id"], f"💳 {html.escape(cu['name'])} говорит, что оплатил(а) долг. Проверьте Kaspi и отметьте оплату в Дәптер.")


# ---------- владелец ----------
async def notify_owner(shop_id: int, text: str) -> bool:
    if not enabled():
        return False
    with session() as c:
        chat = get_shop(c, shop_id).get("owner_chat")
    if not chat:
        return False
    try:
        await app.bot.send_message(chat, text, parse_mode=ParseMode.HTML)
        return True
    except Exception as e:
        log.warning("owner notify failed: %s", e)
        return False


async def send_report(shop_id: int) -> bool:
    return await notify_owner(shop_id, report_text(daily_report(shop_id)))


async def on_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    with session() as c:
        shop = c.execute("SELECT id FROM shop WHERE owner_chat = ?", (update.effective_chat.id,)).fetchone()
    if not shop:
        await update.message.reply_text("Отчёт доступен только владельцу магазина. Подключитесь через «Настройки» в Дәптер AI.")
        return
    await update.message.reply_text(report_text(daily_report(shop["id"])), parse_mode=ParseMode.HTML)


# ---------- запуск вместе с сервером ----------
async def start():
    global app
    if not BOT_TOKEN:
        log.warning("BOT_TOKEN не задан в .env — бот выключен, касса работает без него")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("report", on_report))
    app.add_handler(CallbackQueryHandler(on_consent, pattern=r"^c:"))
    app.add_handler(CallbackQueryHandler(on_paid, pattern=r"^p:"))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log.warning("Telegram-бот @%s запущен", BOT_USERNAME)


async def stop():
    global app
    if app:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        app = None
