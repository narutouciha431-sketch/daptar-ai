"""Разбор фраз продавца: «Айгүл апай, екі нан, бір сүт, қарызға» → покупатель, товары, тип операции.

Работает без интернета и без платного ИИ: правила + нечёткое сравнение слов.
Учитывает ошибки распознавания речи, которые мы увидели в тесте:
слитные слова («екінан»), похожие имена («әйгіл абай»), числа словами на двух языках.
"""
import re
from difflib import SequenceMatcher

# ---------- нормализация ----------
# Казахские буквы → близкие русские, чтобы «сут» и «сүт», «картоп» и «картоп» совпадали
KK_TO_RU = str.maketrans({"ә": "а", "ғ": "г", "қ": "к", "ң": "н", "ө": "о", "ұ": "у", "ү": "у", "һ": "х", "і": "и", "ё": "е"})


def fold(word: str) -> str:
    """Слово для сравнения: нижний регистр, казахские буквы заменены на близкие русские."""
    return word.lower().translate(KK_TO_RU)


def tokenize(text: str) -> list[str]:
    text = text.lower().replace("ё", "е")
    # «1.500» и «1 500» — это тысяча пятьсот, а не два числа
    text = re.sub(r"(\d)[.\s](\d{3})\b", r"\1\2", text)
    return re.findall(r"[a-zа-яәғқңөұүһі]+|\d+(?:[.,]\d+)?", text)


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, fold(a), fold(b)).ratio()


# ---------- числа словами ----------
UNITS = {
    # казахский
    "бір": 1, "бiр": 1, "екі": 2, "үш": 3, "іш": 3, "төрт": 4, "бес": 5, "алты": 6, "жеті": 7, "сегіз": 8, "тоғыз": 9,
    "он": 10, "жиырма": 20, "отыз": 30, "қырық": 40, "елу": 50, "алпыс": 60, "жетпіс": 70, "сексен": 80, "тоқсан": 90,
    # русский
    "один": 1, "одна": 1, "одну": 1, "одно": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
    "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12, "пятнадцать": 15,
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
    "восемьдесят": 80, "девяносто": 90, "сто": 100, "двести": 200, "триста": 300, "четыреста": 400,
    "пятьсот": 500, "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}
HUNDRED = {"жүз": 100}
THOUSAND = {"мың": 1000, "тысяча": 1000, "тысячу": 1000, "тысячи": 1000, "тысяч": 1000}
FRACTIONS = {"жарты": 0.5, "пол": 0.5, "полтора": 1.5, "полкило": 0.5}
NUMBER_WORDS = set(UNITS) | set(HUNDRED) | set(THOUSAND) | set(FRACTIONS)


# Как распознавание речи на практике искажало «в долг» (тесты 14.10)
DEBT_MISHEARD = {"вдолг", "вдок", "толк", "долк", "дольг", "вдолк"}


def is_debt_word(tok: str) -> bool:
    """қарыз, қарызға, қарызын, долг, в долг…"""
    return tok in DEBT_WORDS or tok in DEBT_MISHEARD or fold(tok).startswith("карыз") or tok.startswith("долг")


def is_pay_word(tok: str) -> bool:
    """төледі, заплатила, оплатил, вернул…"""
    f = fold(tok)
    return tok in PAY_WORDS or f.startswith(("толе", "заплат", "оплат", "вернул", "кайтар"))


def is_number(tok: str) -> bool:
    return tok in NUMBER_WORDS or bool(re.fullmatch(r"\d+(?:[.,]\d+)?", tok))


def read_number(tokens: list[str], i: int) -> tuple[float | None, int]:
    """Читает число, начиная с tokens[i] («екі мың бес жүз» → 2500). Возвращает (число, индекс после него)."""
    if i >= len(tokens) or not is_number(tokens[i]):
        return None, i
    if tokens[i] in FRACTIONS:
        return FRACTIONS[tokens[i]], i + 1
    total, current, j = 0, 0, i
    while j < len(tokens) and is_number(tokens[j]) and tokens[j] not in FRACTIONS:
        t = tokens[j]
        if re.fullmatch(r"\d+(?:[.,]\d+)?", t):
            current += float(t.replace(",", "."))
        elif t in UNITS:
            current += UNITS[t]
        elif t in HUNDRED:
            current = (current or 1) * 100
        elif t in THOUSAND:
            total += (current or 1) * 1000
            current = 0
        j += 1
    value = total + current
    return (int(value) if value == int(value) else value), j


# ---------- служебные слова ----------
DEBT_WORDS = {"қарыз", "қарызға", "карызга", "қарызы", "долг", "долги", "насия", "насыя"}
PAY_WORDS = {"төледі", "төледім", "төлеп", "заплатил", "заплатила", "оплатил", "оплатила", "вернул", "вернула", "отдал", "отдала", "қайтарды"}
WHO_OWES = [("кім", "қарыз"), ("кто", "должен"), ("кто", "должны"), ("кім", "қарызы")]
HALF_WORDS = {"жартысын", "жартысы", "половину", "половина"}
UNIT_WORDS = {"кило", "килой", "кг", "килограмм", "дана", "штук", "штуки", "шт", "пачка", "пачки", "қорап", "корап",
              "бутылка", "бутылки", "литр", "литра", "л", "грамм", "г", "пакет", "банка"}
FILLER = {"и", "мен", "және", "в", "на", "еще", "ещё", "тағы", "тоже", "де", "да", "мне", "маған", "берші", "дай", "дайте"}
# Слова, которые означают целую упаковку: «бір қорап жұмыртқа» = одна упаковка, а «8 жұмыртқа» = 8 штук
PACK_WORDS = {"қорап", "корап", "пачка", "пачки", "уп", "упаковка", "упаковки", "лоток", "десяток", "ләмпі", "пакет"}
PACK_SIZE_RE = re.compile(r"(\d+)\s*(?:дана|шт)\b", re.I)


def pack_size(product: dict) -> int | None:
    """«Жұмыртқа 10 дана» → 10: товар в прайсе — упаковка из N штук."""
    m = PACK_SIZE_RE.search(product["name"])
    return int(m.group(1)) if m and int(m.group(1)) > 1 else None


HONORIFICS = {"апай", "абай", "апа", "ағай", "агай", "аға", "тәте", "ата", "әже", "апке", "көке", "бауырым", "қарындас"}


# ---------- товары ----------
def product_keywords(products: list[dict]) -> list[tuple[str, dict]]:
    """Ключевые слова товара: первое слово названия и все синонимы."""
    pairs = []
    for p in products:
        words = [p["name"].split()[0]] + [s.strip() for s in p["synonyms"].split(",") if s.strip()]
        for w in words:
            for part in w.lower().split():
                if len(part) >= 2 and not is_number(part):
                    pairs.append((part, p))
    return pairs


RU_ENDINGS = ("ами", "ями", "ов", "ев", "ей", "ом", "ем", "ам", "ям", "ах", "ях", "а", "я", "ы", "и", "у", "ю", "е", "о", "й")


def stem(word: str) -> str:
    """Грубая основа русского слова: «чая» → «ча», «чай» → «ча», «сосиски» → «сосиск»."""
    for end in RU_ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 2:
            return word[: -len(end)]
    return word


def match_product(tok: str, keywords) -> tuple[dict | None, float]:
    if len(tok) < 2 or tok in NUMBER_WORDS or tok in UNIT_WORDS or tok in PACK_WORDS or tok in FILLER:
        return None, 0.0
    best, score = None, 0.0
    ft = fold(tok)
    for kw, p in keywords:
        fk = fold(kw)
        if ft == fk:
            return p, 1.0
        if len(ft) >= 3 and stem(ft) == stem(fk):
            return p, 0.95
        s = SequenceMatcher(None, ft, fk).ratio()
        # «хлеба» → «хлеб», «сосиски» → «сосиска»: общее начало и короткое окончание
        common = len(_common_prefix(ft, fk))
        if common >= 3 and common >= min(len(ft), len(fk)) - 2:
            s = max(s, 0.9)
        if s > score:
            best, score = p, s
    return (best, score) if score >= 0.78 else (None, score)


def _common_prefix(a: str, b: str) -> str:
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return a[:n]


def split_glued(tokens: list[str], keywords) -> list[str]:
    """«екінан» → «екі», «нан»: распознавание иногда склеивает число и товар."""
    out = []
    for t in tokens:
        done = False
        if t not in NUMBER_WORDS and not match_product(t, keywords)[0]:
            for num in sorted(NUMBER_WORDS, key=len, reverse=True):
                rest = t[len(num):]
                if t.startswith(num) and len(rest) >= 2 and match_product(rest, keywords)[0]:
                    out += [num, rest]
                    done = True
                    break
        if not done:
            out.append(t)
    return out


# ---------- покупатели ----------
def match_customer(name_tokens: list[str], customers: list[dict]) -> tuple[dict | None, float]:
    if not name_tokens:
        return None, 0.0
    phrase = " ".join(name_tokens)
    first = name_tokens[0]
    best, score = None, 0.0
    for c in customers:
        cname = c["name"].lower()
        s = max(similar(phrase, cname), similar(first, cname.split()[0]))
        if s > score:
            best, score = c, s
    return (best, score) if score >= 0.7 else (None, score)


# ---------- главный разбор ----------
def parse(text: str, products: list[dict], customers: list[dict]) -> dict:
    keywords = product_keywords(products)
    tokens = split_glued(tokenize(text), keywords)
    toks_set = set(tokens)

    result = {
        "text": text,
        "intent": "sale",              # sale / payment / who_owes
        "kind": None,                  # debt / paid / None (решает продавец кнопкой)
        "customer": None,              # найденный покупатель
        "new_customer_name": None,     # если такого покупателя ещё нет
        "items": [],
        "half_paid": bool(toks_set & HALF_WORDS),
        "amount": None,                # сумма оплаты долга
        "unknown": [],                 # слова, которые не поняли
    }

    for a, b in WHO_OWES:
        if a in toks_set and b in toks_set:
            result["intent"] = "who_owes"
            return result

    # Имя покупателя — слова в начале фразы до первого числа или товара
    name_tokens = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if is_number(t) or is_debt_word(t) or is_pay_word(t) or t in UNIT_WORDS or match_product(t, keywords)[0]:
            break
        if t not in FILLER:
            name_tokens.append(t)
        i += 1
    core = [t for t in name_tokens if t not in HONORIFICS] or name_tokens
    customer, _ = match_customer(core, customers)
    if not customer and name_tokens and len(name_tokens) <= 3:
        customer, _ = match_customer(name_tokens, customers)
    if customer:
        result["customer"] = {"id": customer["id"], "name": customer["name"]}
    elif name_tokens:
        result["new_customer_name"] = " ".join(w.capitalize() for w in name_tokens)

    # Товары и количества
    qty = None
    unit = None  # единица, названная перед товаром («қорап», «кило»)
    while i < len(tokens):
        t = tokens[i]
        if is_debt_word(t):
            result["kind"] = "debt"
            i += 1
            continue
        if is_pay_word(t):
            result["kind"] = result["kind"] or "paid"
            i += 1
            continue
        if is_number(t):
            qty, i = read_number(tokens, i)
            continue
        if t in UNIT_WORDS or t in PACK_WORDS:
            unit = t
            i += 1
            continue
        if t in FILLER or t in HALF_WORDS:
            i += 1
            continue
        p, _ = match_product(t, keywords)
        if p:
            q = qty if qty else 1
            # «8 жұмыртқа» при товаре «Жұмыртқа 10 дана» — это 8 штук, т. е. 0,8 упаковки
            size = pack_size(p)
            if size and qty and unit not in PACK_WORDS and qty >= 2:
                q = round(qty / size, 2)
            unit = None
            existing = next((it for it in result["items"] if it["product_id"] == p["id"]), None)
            if existing:
                existing["qty"] += q
                existing["amount"] = round(existing["qty"] * existing["price"])
            else:
                result["items"].append({
                    "product_id": p["id"], "name": p["name"], "qty": q, "price": p["price"],
                    "amount": round(q * p["price"]),
                })
            qty = None
        else:
            result["unknown"].append(t)
            unit = None  # «бір қорап сіріңке, сегіз жұмыртқа» — «қорап» относился к непонятному слову
        i += 1

    # «жартысын төледі» — половину заплатили, остальное в долг
    if result["half_paid"] and result["items"]:
        result["kind"] = "debt"

    # «Ерлан қарызын төледі екі мың» — оплата долга, а не продажа
    if any(is_pay_word(t) for t in tokens) and not result["items"] and qty:
        result["intent"] = "payment"
        result["amount"] = qty
        result["kind"] = None
    return result
