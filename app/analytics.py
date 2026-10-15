"""Аналитика для кабинета и генератор демо-истории (помеченной как demo)."""
import random
import secrets
from datetime import date, datetime, timedelta

from .db import BALANCE_SQL, DEMO_CUSTOMERS, DEMO_PRODUCTS, open_debts, session, settle_fifo


def analytics(shop_id: int, days: int = 30) -> dict:
    days = max(7, min(days, 120))
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    week_ago = (date.today() - timedelta(days=6)).isoformat()
    two_weeks = (date.today() - timedelta(days=13)).isoformat()
    with session() as c:
        by_day = {r["d"]: dict(r) for r in c.execute(
            "SELECT date(created_at) AS d, "
            "SUM(CASE WHEN kind = 'paid' THEN total ELSE 0 END) AS sold_paid, "
            "SUM(CASE WHEN kind = 'debt' AND status != 'rejected' THEN total ELSE 0 END) AS sold_debt, "
            "SUM(CASE WHEN kind = 'debt' AND status != 'rejected' THEN total - paid_now ELSE 0 END) AS new_debt, "
            "COUNT(*) AS cnt FROM sale WHERE shop_id = ? AND date(created_at) >= ? GROUP BY d", (shop_id, start))}
        returned = {r["d"]: r["s"] for r in c.execute(
            "SELECT date(created_at) AS d, SUM(amount) AS s FROM payment WHERE shop_id = ? AND date(created_at) >= ? GROUP BY d", (shop_id, start))}
        top = [dict(r) for r in c.execute(
            "SELECT si.name, SUM(si.qty) AS qty, SUM(si.amount) AS amount FROM sale_item si JOIN sale s ON s.id = si.sale_id "
            "WHERE s.shop_id = ? AND date(s.created_at) >= ? AND s.status != 'rejected' GROUP BY si.name ORDER BY amount DESC LIMIT 8", (shop_id, start))]
        week = lambda frm, to: c.execute(
            "SELECT COALESCE(SUM(total),0), COALESCE(SUM(CASE WHEN kind='debt' THEN total - paid_now ELSE 0 END),0), COUNT(*) "
            "FROM sale WHERE shop_id = ? AND date(created_at) BETWEEN ? AND ? AND status != 'rejected'", (shop_id, frm, to)).fetchone()
        ret_week = lambda frm, to: c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payment WHERE shop_id = ? AND date(created_at) BETWEEN ? AND ?", (shop_id, frm, to)).fetchone()[0]
        today = date.today().isoformat()
        prev_end = (date.today() - timedelta(days=7)).isoformat()
        this_w, prev_w = week(week_ago, today), week(two_weeks, prev_end)
        ret_this, ret_prev = ret_week(week_ago, today), ret_week(two_weeks, prev_end)
        debtors = [dict(r) for r in c.execute(
            f"SELECT id, name, ({BALANCE_SQL}) AS balance FROM customer WHERE shop_id = ? AND balance > 0 ORDER BY balance DESC", (shop_id,))]
        # Возраст долгов: по открытым остаткам каждой покупки в долг
        aging = {"0–7 дней": 0, "8–14 дней": 0, "15–30 дней": 0, "больше 30": 0}
        for d in debtors:
            for s in open_debts(c, d["id"]):
                age = (date.today() - date.fromisoformat(s["created_at"][:10])).days
                key = "0–7 дней" if age <= 7 else "8–14 дней" if age <= 14 else "15–30 дней" if age <= 30 else "больше 30"
                aging[key] += s["left"]
        # Сколько долгов возвращается: возвраты / (возвраты + текущий долг) за период
        returned_total = sum(v or 0 for v in returned.values())

    series = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        row = by_day.get(d, {})
        series.append({"day": d, "sold_paid": row.get("sold_paid") or 0, "sold_debt": row.get("sold_debt") or 0,
                       "new_debt": row.get("new_debt") or 0, "returned": returned.get(d) or 0, "count": row.get("cnt") or 0})
    owed = sum(d["balance"] for d in debtors)
    return {
        "days": days, "series": series, "top_products": top, "aging": aging, "debtors": debtors[:8],
        "owed": owed,
        "return_rate": round(returned_total / (returned_total + owed) * 100) if (returned_total + owed) else None,
        "week": {"sold": this_w[0], "new_debt": this_w[1], "count": this_w[2], "returned": ret_this},
        "prev_week": {"sold": prev_w[0], "new_debt": prev_w[1], "count": prev_w[2], "returned": ret_prev},
    }


def seed_demo(shop_id: int, days: int = 30) -> int:
    """Создаёт правдоподобную историю продаж и долгов за N дней. Все записи помечены demo = 1."""
    rnd = random.Random(42)
    with session() as c:
        products = [dict(r) for r in c.execute("SELECT id, name, price FROM product WHERE shop_id = ?", (shop_id,))]
        if not products:
            return 0
        # Демо-долги вешаем только на демо-покупателей: настоящие балансы и напоминания не затрагиваются
        if not c.execute("SELECT 1 FROM customer WHERE shop_id = ? AND demo = 1", (shop_id,)).fetchone():
            c.executemany("INSERT INTO customer (shop_id, name, phone, language, demo) VALUES (?, ?, '', ?, 1)",
                          [(shop_id, n, lang) for n, lang in [("Демо: Айгүл апай", "kk"), ("Демо: Ерлан", "ru"),
                                                              ("Демо: Мадина", "ru"), ("Демо: Нұрлан ағай", "kk")]])
        customers = [r["id"] for r in c.execute("SELECT id FROM customer WHERE shop_id = ? AND demo = 1", (shop_id,))]
        created = 0
        for back in range(days, 0, -1):
            day = datetime.now() - timedelta(days=back)
            weekend = day.weekday() >= 5
            for _ in range(rnd.randint(10, 18) + (5 if weekend else 0)):
                is_debt = rnd.random() < 0.12
                items = rnd.sample(products, rnd.randint(1, 4))
                lines = [(p, rnd.choice([1, 1, 1, 2, 2, 3])) for p in items]
                total = sum(p["price"] * q for p, q in lines)
                at = day.replace(hour=rnd.randint(8, 21), minute=rnd.randint(0, 59), second=0).strftime("%Y-%m-%d %H:%M:%S")
                cid = rnd.choice(customers) if is_debt or rnd.random() < 0.3 else None
                if is_debt:
                    paid_now = rnd.choice([0, 0, 0, total // 2])
                    due = (day + timedelta(days=14)).date().isoformat()
                    status = rnd.choice(["confirmed", "confirmed", "pending"])
                    sid = c.execute(
                        "INSERT INTO sale (shop_id, customer_id, kind, total, paid_now, due_date, status, consent_token, source, raw_text, created_at, demo) "
                        "VALUES (?, ?, 'debt', ?, ?, ?, ?, ?, 'text', 'demo', ?, 1)",
                        (shop_id, cid, total, paid_now, due, status, secrets.token_urlsafe(8), at)).lastrowid
                    # Большинство долгов возвращают через 2–16 дней
                    pay_day = day + timedelta(days=rnd.randint(2, 16))
                    if rnd.random() < 0.85 and pay_day < datetime.now():
                        c.execute("INSERT INTO payment (shop_id, customer_id, amount, method, created_at, demo) VALUES (?, ?, ?, ?, ?, 1)",
                                  (shop_id, cid, total - paid_now, rnd.choice(["cash", "kaspi", "kaspi"]),
                                   pay_day.replace(hour=rnd.randint(9, 20)).strftime("%Y-%m-%d %H:%M:%S")))
                else:
                    sid = c.execute(
                        "INSERT INTO sale (shop_id, customer_id, kind, total, paid_now, status, source, raw_text, created_at, demo) "
                        "VALUES (?, ?, 'paid', ?, ?, 'paid', ?, 'demo', ?, 1)",
                        (shop_id, cid, total, total, rnd.choice(["text", "text", "barcode", "voice"]), at)).lastrowid
                c.executemany("INSERT INTO sale_item (sale_id, product_id, name, qty, price, amount) VALUES (?, ?, ?, ?, ?, ?)",
                              [(sid, p["id"], p["name"], q, p["price"], p["price"] * q) for p, q in lines])
                created += 1
        # Возвраты гасят самые старые долги
        for cid in customers:
            settle_fifo(c, cid)
    return created


def clear_demo(shop_id: int) -> int:
    with session() as c:
        n = c.execute("DELETE FROM sale WHERE shop_id = ? AND demo = 1", (shop_id,)).rowcount
        c.execute("DELETE FROM payment WHERE shop_id = ? AND demo = 1", (shop_id,))
        # Демо-покупатели уходят вместе с историей (если к ним не привязали настоящих записей)
        c.execute("DELETE FROM customer WHERE shop_id = ? AND demo = 1 AND id NOT IN "
                  "(SELECT customer_id FROM sale WHERE customer_id IS NOT NULL UNION SELECT customer_id FROM payment "
                  " UNION SELECT customer_id FROM reminder)", (shop_id,))
        # Настоящие долги, которые закрылись демо-оплатами, снова открываем и пересчитываем
        c.execute("UPDATE sale SET status = CASE WHEN consent_at IS NULL THEN 'pending' ELSE 'confirmed' END "
                  "WHERE shop_id = ? AND kind = 'debt' AND status = 'closed'", (shop_id,))
        for (cid,) in c.execute("SELECT id FROM customer WHERE shop_id = ?", (shop_id,)).fetchall():
            settle_fifo(c, cid)
    return n


def reset_demo(shop_id: int) -> int:
    """Демо-магазин к исходному виду: стандартный прайс и покупатели, история за 30 дней и несколько текущих долгов.
    Всё, что посетители добавили в общий демо-магазин, стирается."""
    with session() as c:
        c.execute("DELETE FROM sale_item WHERE sale_id IN (SELECT id FROM sale WHERE shop_id = ?)", (shop_id,))
        for table in ("sale", "payment", "reminder", "customer", "product"):
            c.execute(f"DELETE FROM {table} WHERE shop_id = ?", (shop_id,))
        c.executemany("INSERT INTO product (shop_id, name, synonyms, price, unit) VALUES (?, ?, ?, ?, ?)",
                      [(shop_id, *p) for p in DEMO_PRODUCTS])
        c.executemany("INSERT INTO customer (shop_id, name, phone, address, language) VALUES (?, ?, ?, ?, ?)",
                      [(shop_id, *cu) for cu in DEMO_CUSTOMERS])
    created = seed_demo(shop_id, 30)
    # Текущие долги у обычных покупателей, чтобы раздел «Долги» выглядел живым
    rnd = random.Random(7)
    with session() as c:
        products = [dict(r) for r in c.execute("SELECT id, name, price FROM product WHERE shop_id = ?", (shop_id,))]
        people = [r["id"] for r in c.execute("SELECT id FROM customer WHERE shop_id = ? AND demo = 0", (shop_id,))]
        now = datetime.now()
        for i, cid in enumerate(people):
            for k in range(rnd.randint(1, 3)):
                back = rnd.randint(1, 12)
                day = now - timedelta(days=back, hours=rnd.randint(0, 8))
                lines = [(p, rnd.choice([1, 1, 2, 3])) for p in rnd.sample(products, rnd.randint(1, 4))]
                total = sum(p["price"] * q for p, q in lines)
                due = (day + timedelta(days=7 if i == len(people) - 1 else 14)).date().isoformat()  # последний — просрочен
                status = "confirmed" if (i + k) % 3 else "pending"
                sid = c.execute(
                    "INSERT INTO sale (shop_id, customer_id, kind, total, paid_now, due_date, status, consent_token, source, raw_text, created_at) "
                    "VALUES (?, ?, 'debt', ?, 0, ?, ?, ?, 'voice', 'demo', ?)",
                    (shop_id, cid, total, due, status, secrets.token_urlsafe(8), day.strftime("%Y-%m-%d %H:%M:%S"))).lastrowid
                c.executemany("INSERT INTO sale_item (sale_id, product_id, name, qty, price, amount) VALUES (?, ?, ?, ?, ?, ?)",
                              [(sid, p["id"], p["name"], q, p["price"], p["price"] * q) for p, q in lines])
    return created
