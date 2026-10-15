"""Тест разбора на реальных результатах распознавания речи (тесты 14.10, две серии по 10 фраз)."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from app.db import DEMO_PRODUCTS
from app.parser import parse

products = [{"id": i + 1, "name": n, "synonyms": s, "price": p} for i, (n, s, p, _) in enumerate(DEMO_PRODUCTS)]
customers = [{"id": 1, "name": "Айгүл апай"}, {"id": 2, "name": "Ерлан"}, {"id": 3, "name": "Мадина"},
             {"id": 4, "name": "Сәуле"}, {"id": 5, "name": "Нұрлан ағай"}]
phrases = [
    # серия 2 (исправленная страница)
    "әйгілі абай екінан бір сүт қарызға",
    "ерлан сигареті иевада вдок",
    "мәдина дувақылап і стасиске қарызға",
    "нұрлан ағай бір қорап шай зе бір кило айтқан қарызға",
    "сәуле іш кило картоп өсті",
    "ирлан қарызын төледі екі бес жү",
    "Ерлан сигареты и вода в долг",
    "Айгуль заплатила 1.500",
    "әйгілі экономикасы",
    "нұрландағы бір кішәйбір киі қанат қарызға",
    # серия 1b
    "әйгілабай екі нан бір сүт қарызға",
    "Ерлан сигареты и вода в толк",
    "сәуле үш кило картоп жартысын төледі",
    "ирлан қарызын төледі екі мың",
    "кім қарыз",
    "Мадина два хлеба и сосиски",
    "нұрлан ағай бір картоп шәй қант қарызға",
    "Айгуль заплатил 1.500",
]
for ph in phrases:
    r = parse(ph, products, customers)
    who = r["customer"]["name"] if r["customer"] else (f"НОВЫЙ:{r['new_customer_name']}" if r["new_customer_name"] else "—")
    items = ", ".join(f"{it['name']}×{it['qty']}" for it in r["items"])
    extra = f" сумма={r['amount']}" if r["amount"] else ""
    print(f"{ph}\n   → {r['intent']}/{r['kind']} | {who} | [{items}]{extra} | не понято={r['unknown']}")
