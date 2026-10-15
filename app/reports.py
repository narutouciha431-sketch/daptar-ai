"""Отчёт владельцу: выручка, долги, возвраты, налог по ставке района, запас до лимита упрощёнки."""
import html
from datetime import date

from .config import SERVICE_RATE, SIMPLIFIED_LIMIT
from .db import BALANCE_SQL, get_shop, session
from .texts import money


def daily_report(shop_id: int, day: str | None = None) -> dict:
    day = day or date.today().isoformat()
    with session() as c:
        shop = get_shop(c, shop_id)
        one = lambda sql, *a: c.execute(sql, a).fetchone()[0] or 0
        sold = one("SELECT SUM(total) FROM sale WHERE shop_id = ? AND date(created_at) = ?", shop_id, day)
        sales_count = one("SELECT COUNT(*) FROM sale WHERE shop_id = ? AND date(created_at) = ?", shop_id, day)
        new_debt = one("SELECT SUM(total - paid_now) FROM sale WHERE shop_id = ? AND kind = 'debt' AND status != 'rejected' "
                       "AND date(created_at) = ?", shop_id, day)
        new_debt_count = one("SELECT COUNT(*) FROM sale WHERE shop_id = ? AND kind = 'debt' AND status != 'rejected' "
                             "AND date(created_at) = ?", shop_id, day)
        returned = one("SELECT SUM(amount) FROM payment WHERE shop_id = ? AND date(created_at) = ?", shop_id, day)
        cash_in = one("SELECT SUM(paid_now) FROM sale WHERE shop_id = ? AND date(created_at) = ?", shop_id, day) + returned
        debtors = c.execute(
            f"SELECT name, ({BALANCE_SQL}) AS balance, "
            "(SELECT MIN(due_date) FROM sale s WHERE s.customer_id = customer.id AND s.kind = 'debt' "
            " AND s.status IN ('pending', 'confirmed')) AS due "
            "FROM customer WHERE shop_id = ? AND balance > 0 ORDER BY balance DESC", (shop_id,)
        ).fetchall()
        month = day[:7]
        month_paid = one("SELECT SUM(paid_now) FROM sale WHERE shop_id = ? AND strftime('%Y-%m', created_at) = ?", shop_id, month)
        month_back = one("SELECT SUM(amount) FROM payment WHERE shop_id = ? AND strftime('%Y-%m', created_at) = ?", shop_id, month)
        year_sold = one("SELECT SUM(total) FROM sale WHERE shop_id = ? AND strftime('%Y', created_at) = ?", shop_id, day[:4])

    owed = sum(d["balance"] for d in debtors)
    overdue = [dict(d) for d in debtors if d["due"] and d["due"] < day]
    return {
        "day": day,
        "shop": shop["name"],
        "district": shop["district"],
        "sold": sold,
        "sales_count": sales_count,
        "cash_in": cash_in,
        "new_debt": new_debt,
        "new_debt_count": new_debt_count,
        "returned": returned,
        "owed": owed,
        "debtors_count": len(debtors),
        "overdue": overdue,
        "overdue_sum": sum(d["balance"] for d in overdue),
        "tax_rate": shop["tax_rate"],
        "tax_today": round(sold * shop["tax_rate"]),
        "year_sold": year_sold,
        "limit_left": max(SIMPLIFIED_LIMIT - year_sold, 0),
        "language": shop["language"],
        "service_month": month,
        "service_paid": month_paid,
        "service_back": month_back,
        "service_rate": shop.get("service_rate") or SERVICE_RATE,
        "service_fee": round((month_paid + month_back) * (shop.get("service_rate") or SERVICE_RATE)),
    }


def report_text(r: dict) -> str:
    d, m = r["day"][8:10], r["day"][5:7]
    r = {**r, "shop": html.escape(r["shop"])}  # название магазина идёт в HTML-сообщение Telegram
    pct = f"{r['tax_rate'] * 100:g}%"
    if r["language"] == "ru":
        lines = [
            f"📒 <b>«{r['shop']}», отчёт за {d}.{m}</b>",
            f"Продано: <b>{money(r['sold'])}</b> ({r['sales_count']} покупок)",
            f"Получено денег: {money(r['cash_in'])}",
            f"Новые долги: {money(r['new_debt'])} ({r['new_debt_count']})",
            f"Вернули долгов: <b>{money(r['returned'])}</b>",
            f"Всего вам должны: <b>{money(r['owed'])}</b> ({r['debtors_count']} чел.)",
        ]
        if r["overdue"]:
            lines.append(f"⚠️ Просрочено: {len(r['overdue'])} чел., {money(r['overdue_sum'])}")
        lines.append(f"Оплата сервиса Дәптер за месяц ({r['service_rate'] * 100:g}%): {money(r['service_fee'])}")
        if r['year_sold'] > SIMPLIFIED_LIMIT / 2:
            lines.append(f"До лимита упрощёнки за год осталось: {money(r['limit_left'])}")
    else:
        lines = [
            f"📒 <b>«{r['shop']}», {d}.{m} есебі</b>",
            f"Сатылды: <b>{money(r['sold'])}</b> ({r['sales_count']} сатып алу)",
            f"Түскен ақша: {money(r['cash_in'])}",
            f"Жаңа қарыздар: {money(r['new_debt'])} ({r['new_debt_count']})",
            f"Қайтарылған қарыз: <b>{money(r['returned'])}</b>",
            f"Барлық қарыз: <b>{money(r['owed'])}</b> ({r['debtors_count']} адам)",
        ]
        if r["overdue"]:
            lines.append(f"⚠️ Мерзімі өткен: {len(r['overdue'])} адам, {money(r['overdue_sum'])}")
        lines.append(f"Дәптер қызметінің айлық ақысы ({r['service_rate'] * 100:g}%): {money(r['service_fee'])}")
        if r['year_sold'] > SIMPLIFIED_LIMIT / 2:
            lines.append(f"Жылдық жеңілдетілген режим шегіне дейін: {money(r['limit_left'])}")
    return "\n".join(lines)
