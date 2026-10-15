"""ИИ-слой Дәптер AI на Google Gemini (бесплатный уровень).

Три задачи:
1. разбор трудных фраз продавца, которые не поняли правила;
2. фото ценника или упаковки → название, цена, синонимы;
3. советы владельцу по обезличенным цифрам магазина.
ИИ — улучшение, а не точка поломки: нет ключа, сети или лимита — касса работает на правилах.
"""
import json
import logging
import os
import time

import httpx

from . import config  # noqa: F401  — загружает .env с ключом

log = logging.getLogger("daptar.ai")

API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
# Быстрая модель основная, обычная Flash — запасная (бывает перегружена)
MODELS = [m.strip() for m in os.getenv("GEMINI_MODELS", "gemini-flash-lite-latest,gemini-flash-latest").split(",") if m.strip()]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def enabled() -> bool:
    return bool(API_KEY)


async def _ask(parts: list, schema: dict | None = None, timeout: float = 12) -> dict | str | None:
    """Запрос к Gemini. Возвращает JSON (если задана схема) или текст. None — если ИИ недоступен."""
    if not API_KEY:
        return None
    body = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.2}}
    if schema:
        body["generationConfig"].update({"responseMimeType": "application/json", "responseSchema": schema})
    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in MODELS:
            try:
                t = time.time()
                r = await client.post(URL.format(model=model), json=body, headers={"x-goog-api-key": API_KEY})
                if r.status_code in (429, 500, 503):
                    log.warning("Gemini %s: %s, пробую следующую модель", model, r.status_code)
                    continue
                r.raise_for_status()
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                log.info("Gemini %s ответил за %.1f с", model, time.time() - t)
                return json.loads(text) if schema else text.strip()
            except Exception as e:
                log.warning("Gemini %s: ошибка %s", model, e)
    return None


# ---------- 1. разбор фразы ----------
PARSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "intent": {"type": "STRING", "enum": ["sale", "payment", "who_owes"]},
        "kind": {"type": "STRING", "enum": ["debt", "paid", "unknown"]},
        "customer": {"type": "STRING", "description": "имя покупателя из списка или новое имя, пусто если нет"},
        "items": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "product": {"type": "STRING", "description": "точное название товара из прайса"},
            "qty": {"type": "NUMBER"}}, "required": ["product", "qty"]}},
        "amount": {"type": "NUMBER", "description": "сумма оплаты долга в тенге, если это оплата"},
        "half_paid": {"type": "BOOLEAN"},
    },
    "required": ["intent", "kind", "items"],
}


async def parse_phrase(text: str, products: list[dict], customers: list[dict]) -> dict | None:
    price_list = "\n".join(f"- {p['name']} (синонимы: {p['synonyms']})" for p in products)
    people = ", ".join(c["name"] for c in customers) or "нет"
    prompt = f"""Ты помощник продавца сельского магазина в Казахстане. Продавец сказал фразу на казахском, русском или вперемешку.
Фраза получена распознаванием речи и может содержать ошибки: слитные слова («екінан» = «екі нан»), искажённые слова, пропуски.
Определи покупателя, товары и количество, и это долг (қарыз, в долг) или оплата.
Если человек возвращает долг («қарызын төледі», «заплатила»), intent = payment и amount = сумма.
Если спрашивают, кто должен («кім қарыз»), intent = who_owes.
Товары бери ТОЛЬКО из прайса, пиши точное название из прайса. Если товара нет в прайсе — не выдумывай его.
Количество бери ровно как сказано, не умножай и не складывай одну позицию дважды.
Если товар в прайсе — упаковка (например «Жұмыртқа 10 дана»), а покупатель назвал штуки («8 яиц», «сегіз жұмыртқа»),
то qty = штуки / размер упаковки (8 / 10 = 0.8). Если сказано «бір қорап», «пачка», «десяток» — это целая упаковка.
«Кило», «кг» относятся к весовым товарам: «5 кг картошки» = 5.
Покупателя выбери из списка, если похоже по звучанию; иначе запиши имя как услышано.

Прайс:
{price_list}

Известные покупатели: {people}

Фраза: «{text}»"""
    return await _ask([{"text": prompt}], PARSE_SCHEMA)


# ---------- 2. фото ценника ----------
PHOTO_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "name": {"type": "STRING", "description": "короткое название товара, как его называют в магазине, на казахском или русском"},
        "price": {"type": "INTEGER", "description": "цена в тенге, если видна на ценнике, иначе 0"},
        "unit": {"type": "STRING", "description": "шт, кг, уп, пачка, л"},
        "synonyms": {"type": "STRING", "description": "3-5 синонимов через запятую на казахском и русском, как покупатели называют товар"},
        "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
    },
    "required": ["name", "price", "unit", "synonyms", "confidence"],
}


async def read_photo(image_b64: str, mime: str) -> dict | None:
    prompt = ("На фото ценник или упаковка товара из магазина в Казахстане. Определи товар и цену в тенге. "
              "Название дай коротко, как в прайсе магазина у дома (например «Сүт 1 л», «Нан», «Шай 250 г»). "
              "Если цены не видно, price = 0. Не выдумывай цену.")
    return await _ask([{"text": prompt}, {"inline_data": {"mime_type": mime, "data": image_b64}}], PHOTO_SCHEMA, timeout=20)


MATCH_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "seen": {"type": "STRING", "description": "что видно на фото, 2-5 слов"},
        "candidates": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "id": {"type": "INTEGER"}, "confidence": {"type": "NUMBER", "description": "0..1"}}, "required": ["id", "confidence"]}},
    },
    "required": ["seen", "candidates"],
}


async def match_photo(image_b64: str, mime: str, products: list[dict]) -> dict | None:
    """Фото товара → до 3 похожих товаров из прайса магазина (по id). Чужих товаров не придумываем."""
    catalog = "\n".join(f"{p['id']}: {p['name']}" + (f" ({p['synonyms']})" if p.get("synonyms") else "") for p in products)
    prompt = ("На фото товар из магазина у дома в Казахстане. Ниже прайс магазина в формате «id: название (синонимы)». "
              "Выбери до 3 товаров из прайса, которые больше всего похожи на товар на фото, от самого вероятного. "
              "Если ничего не похоже — верни пустой список. Используй только id из прайса.\n\n" + catalog)
    return await _ask([{"text": prompt}, {"inline_data": {"mime_type": mime, "data": image_b64}}], MATCH_SCHEMA, timeout=20)


# ---------- 3. советы владельцу ----------
INSIGHTS_SCHEMA = {
    "type": "OBJECT",
    "properties": {"tips": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "title": {"type": "STRING"}, "text": {"type": "STRING"}}, "required": ["title", "text"]}}},
    "required": ["tips"],
}


async def insights(stats: dict, language: str) -> list[dict] | None:
    lang = "на казахском языке" if language == "kk" else "на русском языке"
    prompt = f"""Ты советник владельца маленького магазина у дома в Таразе (Казахстан). Ниже обезличенные цифры магазина за 30 дней.
Дай 3–5 коротких практичных советов {lang}: как вернуть долги быстрее, что закупать, на что обратить внимание.
Каждый совет опирай на конкретные цифры из данных. Без процентов и пени по долгам — долг держится на доверии соседей.
Покупателей называй ровно так, как они обозначены в данных (П1, П2 и т. д.), без слов «покупатель номер».
Не выдумывай данных, которых нет. Пиши просто, как для человека без экономического образования.

Данные: {json.dumps(stats, ensure_ascii=False)}"""
    r = await _ask([{"text": prompt}], INSIGHTS_SCHEMA, timeout=25)
    return r["tips"] if r else None
