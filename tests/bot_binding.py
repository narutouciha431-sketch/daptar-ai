"""Проверка привязки Telegram на копии базы (настоящая база не меняется).

Сценарии: демо-магазин не подключается; один Telegram — один магазин; чужой Telegram
не может подтвердить долг покупателя; кнопка «Я оплатил» работает только у своего покупателя.
"""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import db  # noqa: E402

tmp = Path(tempfile.mkdtemp()) / "test.db"
shutil.copy(db.DB_PATH, tmp)
db.DB_PATH = tmp
from app import bot  # noqa: E402

bot.hub.broadcast = AsyncMock()
bot.notify_owner = AsyncMock(return_value=True)
problems = []


def check(cond, text):
    print(("✅ " if cond else "❌ ") + text)
    if not cond:
        problems.append(text)


def message_update(chat_id, username, args):
    msg = SimpleNamespace(reply_text=AsyncMock())
    upd = SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id), effective_user=SimpleNamespace(username=username), message=msg)
    return upd, SimpleNamespace(args=args), msg


def callback_update(chat_id, username, data):
    q = SimpleNamespace(data=data, answer=AsyncMock(), edit_message_reply_markup=AsyncMock(),
                        message=SimpleNamespace(chat=SimpleNamespace(id=chat_id), reply_text=AsyncMock()),
                        from_user=SimpleNamespace(username=username))
    return SimpleNamespace(callback_query=q), q


async def main():
    with db.session() as c:
        demo = c.execute("SELECT shop.id, owner_secret FROM shop JOIN user ON user.id = shop.user_id WHERE email = ?", (db.DEMO_EMAIL,)).fetchone()
        c.execute("INSERT INTO user (email, full_name, phone, pw_hash) VALUES ('bind@test.kz', 'Тест Тест', '+77010000000', 'x')")
        uid = c.execute("SELECT id FROM user WHERE email = 'bind@test.kz'").fetchone()[0]
    with db.session() as c:
        s1 = db.create_shop(c, uid, "Тест-1")
        s2 = db.create_shop(c, uid, "Тест-2")
        sec = {r["id"]: r["owner_secret"] for r in c.execute("SELECT id, owner_secret FROM shop WHERE id IN (?, ?)", (s1, s2))}

    upd, ctx, msg = message_update(111, "owner_a", ["owner_" + demo["owner_secret"]])
    await bot.on_start(upd, ctx)
    with db.session() as c:
        check(c.execute("SELECT owner_chat FROM shop WHERE id = ?", (demo["id"],)).fetchone()[0] is None, "демо-магазин не привязывается к Telegram")

    await bot.on_start(*message_update(222, "owner_b", ["owner_" + sec[s1]])[:2])
    await bot.on_start(*message_update(222, "owner_b", ["owner_" + sec[s2]])[:2])
    with db.session() as c:
        o1, o2 = (c.execute("SELECT owner_chat, owner_username FROM shop WHERE id = ?", (i,)).fetchone() for i in (s1, s2))
    check(o1["owner_chat"] is None and o2["owner_chat"] == 222 and o2["owner_username"] == "owner_b",
          "один Telegram — один магазин: при подключении ко второму отвязан от первого, @username сохранён")

    with db.session() as c:
        cid = c.execute("INSERT INTO customer (shop_id, name, language) VALUES (?, 'Покупатель', 'kk')", (s2,)).lastrowid
        mk = lambda tok: c.execute("INSERT INTO sale (shop_id, customer_id, kind, total, paid_now, status, consent_token, due_date) "
                                   "VALUES (?, ?, 'debt', 1000, 0, 'pending', ?, '2026-10-30')", (s2, cid, tok)).lastrowid
        mk("tokA"); mk("tokB")
    upd, q = callback_update(333, "buyer", "c:tokA:y")
    await bot.on_consent(upd, None)
    with db.session() as c:
        row = c.execute("SELECT tg_chat_id, tg_username FROM customer WHERE id = ?", (cid,)).fetchone()
    check(row["tg_chat_id"] == 333 and row["tg_username"] == "buyer", "покупатель привязан к своему Telegram после «Растаймын»")

    upd, q = callback_update(444, "stranger", "c:tokB:y")
    await bot.on_consent(upd, None)
    with db.session() as c:
        st = c.execute("SELECT status FROM sale WHERE consent_token = 'tokB'").fetchone()[0]
    check(st == "pending", "чужой Telegram не может подтвердить долг этого покупателя")

    upd, ctx, msg = message_update(444, "stranger", ["d_tokB"])
    await bot.on_start(upd, ctx)
    check(bot.T.OTHER_ACCOUNT in msg.reply_text.call_args[0][0], "чужой Telegram по QR видит «привязан к другому аккаунту»")

    bot.notify_owner.reset_mock()
    upd, q = callback_update(444, "stranger", f"p:{cid}")
    await bot.on_paid(upd, None)
    check(not bot.notify_owner.called, "«Я оплатил» из чужого Telegram не уведомляет владельца")
    upd, q = callback_update(333, "buyer", f"p:{cid}")
    await bot.on_paid(upd, None)
    check(bot.notify_owner.called and bot.notify_owner.call_args[0][0] == s2, "«Я оплатил» от своего покупателя уходит владельцу своего магазина")


asyncio.run(main())
print(f"\nИтог: {'0 проблем' if not problems else str(len(problems)) + ' проблем'}")
