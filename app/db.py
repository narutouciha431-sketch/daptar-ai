"""База данных Дәптер AI: SQLite в одном файле.

Несколько аккаунтов: у каждого пользователя свой магазин, все данные привязаны к shop_id.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "daptar.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL UNIQUE,
    full_name   TEXT NOT NULL,
    phone       TEXT NOT NULL,
    pw_hash     TEXT NOT NULL,                   -- pbkdf2$итерации$соль$хеш, сам пароль не храним
    is_blocked  INTEGER NOT NULL DEFAULT 0,      -- заблокирован администратором
    last_login  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS auth_session (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    expires_at  TEXT NOT NULL
);

-- Одноразовый вход для телефона-сканера (QR на кассе)
CREATE TABLE IF NOT EXISTS login_token (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shop (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES user(id),
    name        TEXT NOT NULL DEFAULT 'Мой магазин',
    district    TEXT NOT NULL DEFAULT 'Тараз',
    tax_rate    REAL NOT NULL DEFAULT 0.04,      -- ставка упрощёнки, доля (базовая 4%, районы могут снизить)
    kaspi_link  TEXT NOT NULL DEFAULT '',        -- ссылка или номер Kaspi для оплаты долга
    language    TEXT NOT NULL DEFAULT 'kk',      -- kk / ru
    owner_chat  INTEGER,                         -- Telegram chat_id владельца
    owner_secret TEXT,                           -- секрет для подключения владельца к боту
    report_time TEXT NOT NULL DEFAULT '21:00',   -- когда присылать вечерний отчёт
    report_sent_on TEXT,                         -- дата последнего отправленного отчёта
    owner_username TEXT,                         -- @username владельца в Telegram
    service_kaspi  TEXT NOT NULL DEFAULT '',     -- реквизиты оплаты сервиса Дәптер
    service_name   TEXT NOT NULL DEFAULT '',
    service_rate   REAL NOT NULL DEFAULT 0.01
);

-- Фото товаров храним в базе: на сервере файлы на диске не сохраняются
CREATE TABLE IF NOT EXISTS product_photo (
    product_id  INTEGER PRIMARY KEY REFERENCES product(id),
    data        BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS product (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id     INTEGER NOT NULL DEFAULT 1 REFERENCES shop(id),
    name        TEXT NOT NULL,
    synonyms    TEXT NOT NULL DEFAULT '',        -- через запятую: «хлеб, нан»
    price       INTEGER NOT NULL CHECK (price >= 0),
    unit        TEXT NOT NULL DEFAULT 'шт',
    barcode     TEXT,
    photo       INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (shop_id, barcode)                    -- штрихкод уникален внутри одного магазина
);

CREATE TABLE IF NOT EXISTS customer (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id     INTEGER NOT NULL DEFAULT 1 REFERENCES shop(id),
    name        TEXT NOT NULL,
    phone       TEXT NOT NULL DEFAULT '',        -- переводы Kaspi идут по номеру телефона
    address     TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    language    TEXT NOT NULL DEFAULT 'kk',
    tg_chat_id  INTEGER,                         -- появляется после подтверждения долга в боте
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    demo        INTEGER NOT NULL DEFAULT 0,      -- демо-покупатель для истории графиков
    tg_username TEXT                             -- @username покупателя в Telegram
);

-- Любая продажа: оплачено сразу или в долг
CREATE TABLE IF NOT EXISTS sale (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id       INTEGER NOT NULL DEFAULT 1 REFERENCES shop(id),
    customer_id   INTEGER REFERENCES customer(id),
    kind          TEXT NOT NULL CHECK (kind IN ('paid', 'debt')),
    total         INTEGER NOT NULL,
    paid_now      INTEGER NOT NULL DEFAULT 0,    -- сколько заплатили сразу (частичная оплата)
    due_date      TEXT,                          -- срок возврата долга
    status        TEXT NOT NULL DEFAULT 'paid',  -- paid / pending / confirmed / rejected / closed
    consent_token TEXT UNIQUE,                   -- для QR-согласия покупателя
    consent_at    TEXT,
    source        TEXT NOT NULL DEFAULT 'text',  -- text / voice / barcode
    raw_text      TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    demo          INTEGER NOT NULL DEFAULT 0,    -- демо-история для показа графиков
    client_ref    TEXT                           -- номер операции от кассы (защита от двойного нажатия)
);

CREATE TABLE IF NOT EXISTS sale_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id     INTEGER NOT NULL REFERENCES sale(id) ON DELETE CASCADE,
    product_id  INTEGER REFERENCES product(id),
    name        TEXT NOT NULL,
    qty         REAL NOT NULL,
    price       INTEGER NOT NULL,
    amount      INTEGER NOT NULL
);

-- Возвраты долгов
CREATE TABLE IF NOT EXISTS payment (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id     INTEGER NOT NULL DEFAULT 1 REFERENCES shop(id),
    customer_id INTEGER NOT NULL REFERENCES customer(id),
    amount      INTEGER NOT NULL CHECK (amount > 0),
    method      TEXT NOT NULL DEFAULT 'cash',    -- cash / kaspi
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    demo        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reminder (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id     INTEGER NOT NULL DEFAULT 1 REFERENCES shop(id),
    customer_id INTEGER NOT NULL REFERENCES customer(id),
    text        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft',   -- draft / sent
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    sent_at     TEXT
);
"""

# Демо-аккаунт: магазин «Береке», будто уже несколько недель работает. Пароль — в README.md
DEMO_EMAIL = "demo@daptar.kz"
DEMO_PASSWORD = "Taraz-Demo-2026"
DEMO_USER = ("Демо Дәптер", "+7 701 000 00 00")

# Демо-прайс магазина у дома. Цены условные, владелец меняет их под себя.
DEMO_PRODUCTS = [
    ("Нан", "хлеб, батон, нан ақ", 200, "шт"),
    ("Сүт 1 л", "молоко, сут, сүт", 550, "шт"),
    ("Жұмыртқа 10 дана", "яйца, яйцо, яиц, яички, жумыртка, жұмыртқа", 900, "уп"),
    ("Шай 250 г", "чай, чая, шай", 1200, "шт"),
    ("Қант 1 кг", "сахар, кант, қант", 650, "кг"),
    ("Сосиска 1 кг", "сосиски, сосиска", 2500, "кг"),
    ("Су 1,5 л", "вода, су", 300, "шт"),
    ("Картоп 1 кг", "картошка, картофель, картоп", 250, "кг"),
    ("Сары май 200 г", "масло, сливочное масло, май", 1300, "шт"),
    ("Макарон 400 г", "макароны, макарон", 450, "шт"),
    ("Ұн 2 кг", "мука, ун, ұн", 900, "шт"),
    ("Күріш 1 кг", "рис, куриш, күріш", 700, "кг"),
    ("Сигарет", "сигареты, сигарета, темекі", 900, "пачка"),
]

# Демо-покупатели (вымышленные) для показа на защите
DEMO_CUSTOMERS = [
    ("Айгүл апай", "+7 701 000 00 01", "Абай көшесі, 12", "kk"),
    ("Ерлан", "+7 702 000 00 02", "5-үй", "ru"),
    ("Мадина", "+7 705 000 00 03", "", "ru"),
    ("Сәуле", "+7 707 000 00 04", "Төле би, 40", "kk"),
    ("Нұрлан ағай", "", "", "kk"),
]

# Долг покупателя = долги (минус оплаченное сразу, без отклонённых) минус возвраты
BALANCE_SQL = """
    COALESCE((SELECT SUM(s.total - s.paid_now) FROM sale s
              WHERE s.customer_id = customer.id AND s.kind = 'debt' AND s.status != 'rejected'), 0)
  - COALESCE((SELECT SUM(p.amount) FROM payment p WHERE p.customer_id = customer.id), 0)
"""


# ---------- пароли ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2$200000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(test.hex(), digest)
    except (ValueError, TypeError):
        return False


# ---------- помощники ----------
def customer_balance(c: sqlite3.Connection, cid: int) -> int:
    row = c.execute(f"SELECT ({BALANCE_SQL}) FROM customer WHERE id = ?", (cid,)).fetchone()
    return row[0] if row else 0


def settle_fifo(c: sqlite3.Connection, cid: int) -> None:
    """Оплаты гасят сначала самые старые долги: полностью покрытые закрываем, остальные остаются открытыми."""
    paid_left = c.execute("SELECT COALESCE(SUM(amount), 0) FROM payment WHERE customer_id = ?", (cid,)).fetchone()[0]
    for s in c.execute("SELECT id, total - paid_now AS debt, status FROM sale WHERE customer_id = ? AND kind = 'debt' "
                       "AND status != 'rejected' ORDER BY created_at, id", (cid,)).fetchall():
        if paid_left >= s["debt"]:
            paid_left -= s["debt"]
            if s["status"] in ("pending", "confirmed"):
                c.execute("UPDATE sale SET status = 'closed' WHERE id = ?", (s["id"],))
        else:
            break


def open_debts(c: sqlite3.Connection, cid: int) -> list[dict]:
    """Открытые долги покупателя с остатком: частичная оплата уменьшает самый старый."""
    rows = [dict(r) for r in c.execute(
        "SELECT id, total - paid_now AS debt, due_date, created_at, status FROM sale WHERE customer_id = ? AND kind = 'debt' "
        "AND status IN ('pending', 'confirmed') ORDER BY created_at, id", (cid,))]
    excess = sum(r["debt"] for r in rows) - customer_balance(c, cid)
    for r in rows:
        cut = min(excess, r["debt"])
        r["left"] = r["debt"] - cut
        excess -= cut
    return [r for r in rows if r["left"] > 0]


def get_shop(c: sqlite3.Connection, shop_id: int) -> dict:
    row = c.execute("SELECT * FROM shop WHERE id = ?", (shop_id,)).fetchone()
    return dict(row) if row else {}


def create_shop(c: sqlite3.Connection, user_id: int, name: str) -> int:
    return c.execute("INSERT INTO shop (user_id, name, owner_secret) VALUES (?, ?, ?)",
                     (user_id, name, secrets.token_urlsafe(9))).lastrowid


# ---------- облачная база Turso (на сервере) ----------
# Если в окружении есть TURSO_URL — работаем с облачной базой (тот же SQLite, но в облаке Turso),
# иначе — с локальным файлом data/daptar.db. SQL-запросы одинаковые для обоих.
TURSO_URL = os.getenv("TURSO_URL", "").strip()
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "").strip()


# Облако Turso живёт по UTC, а «localtime» там — тоже UTC. Казахстан — UTC+5 круглый год.
_LOCALTIME = re.compile(r"(date(?:time)?)\('now',\s*'localtime'\)")


def _kz_time(sql: str) -> str:
    return _LOCALTIME.sub(lambda m: m.group(1) + "('now', '+5 hours')", sql)


class Row(tuple):
    """Строка результата как у sqlite3.Row: r[0], r["name"], dict(r), распаковка в кортеж."""
    _index: dict

    def __new__(cls, values, index):
        row = super().__new__(cls, values)
        row._index = index
        return row

    def __getitem__(self, key):
        return super().__getitem__(self._index[key] if isinstance(key, str) else key)

    def keys(self):
        return list(self._index)


class Cursor:
    """Обёртка курсора libsql: строки-Row, перебор циклом, lastrowid/rowcount."""

    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = cur.lastrowid
        self.rowcount = cur.rowcount
        desc = cur.description or ()
        self._index = {d[0]: i for i, d in enumerate(desc)}

    def _wrap(self, r):
        return None if r is None else Row(r, self._index)

    def fetchone(self):
        return self._wrap(self._cur.fetchone())

    def fetchall(self):
        return [Row(r, self._index) for r in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class TursoConnection:
    """Соединение с Turso с тем же интерфейсом, что использует код: execute, executemany, commit, close."""

    # Подключение к облаку дорогое (~0,15 с), поэтому держим одно открытое на каждый поток и используем повторно
    _local = threading.local()

    def __init__(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            import libsql  # нужен только на сервере
            conn = self._local.conn = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
        self._conn = conn

    def execute(self, sql, params=()):
        try:
            return Cursor(self._conn.execute(_kz_time(sql), tuple(params)))
        except ValueError as e:  # libsql сообщает о нарушении ограничений как ValueError
            if "constraint" in str(e).lower():
                raise sqlite3.IntegrityError(str(e)) from e
            self._local.conn = None  # связь могла оборваться — следующий запрос подключится заново
            raise
        except Exception:
            self._local.conn = None
            raise

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            self._local.conn = None

    def executemany(self, sql, seq):
        for params in seq:
            self.execute(sql, params)

    def executescript(self, script):
        self._conn.executescript(_kz_time(script))

    def commit(self):
        self._conn.commit()

    def close(self):
        pass  # подключение остаётся открытым для следующих запросов этого потока


def connect() -> sqlite3.Connection:
    if TURSO_URL:
        conn = TursoConnection()
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()  # незавершённые изменения не должны попасть в следующий запрос
        raise
    finally:
        conn.close()


# ---------- миграция со старой версии (один магазин) ----------
def _columns(c, table: str) -> set[str]:
    return {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}


def _rebuild(c, table: str, keep: list[str]):
    """Пересоздаёт таблицу по новой схеме, перенося данные (SQLite не умеет менять ограничения).
    legacy_alter_table — чтобы ссылки из других таблиц не «переехали» на временную *_old."""
    c.execute("PRAGMA legacy_alter_table = ON")
    c.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
    c.executescript(SCHEMA)  # создаст новую таблицу
    cols = ", ".join(keep)
    c.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM {table}_old")
    c.execute(f"DROP TABLE {table}_old")
    c.execute("PRAGMA legacy_alter_table = OFF")


def migrate(c):
    tables = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "shop" not in tables:
        return
    c.execute("PRAGMA foreign_keys = OFF")
    shop_sql = c.execute("SELECT sql FROM sqlite_master WHERE name = 'shop'").fetchone()["sql"]
    if "CHECK (id = 1)" in shop_sql:
        old = _columns(c, "shop")
        _rebuild(c, "shop", [x for x in ["id", "name", "district", "tax_rate", "kaspi_link", "language", "owner_chat",
                                         "owner_secret", "report_time", "report_sent_on"] if x in old])
    if "product" in tables and "shop_id" not in _columns(c, "product"):
        old = _columns(c, "product")
        _rebuild(c, "product", [x for x in ["id", "name", "synonyms", "price", "unit", "barcode", "photo", "created_at"] if x in old])
    # Ремонт: в первой версии миграции ссылки позиций продаж «уехали» на product_old
    for (name, sql) in c.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall():
        if sql and "_old\"" in sql and not name.endswith("_old"):
            _rebuild(c, name, [x for x in _columns(c, name)])
    for table in ("customer", "sale", "payment", "reminder"):
        if table in tables and "shop_id" not in _columns(c, table):
            c.execute(f"ALTER TABLE {table} ADD COLUMN shop_id INTEGER NOT NULL DEFAULT 1")
    for table in ("sale", "payment", "customer"):
        if table in tables and "demo" not in _columns(c, table):
            c.execute(f"ALTER TABLE {table} ADD COLUMN demo INTEGER NOT NULL DEFAULT 0")
    # Номер операции от кассы: повторное нажатие «В долг» не создаёт второй долг
    if "sale" in tables and "client_ref" not in _columns(c, "sale"):
        c.execute("ALTER TABLE sale ADD COLUMN client_ref TEXT")
    # Telegram: к какому @username привязан чат владельца и покупателя
    if "shop" in tables and "owner_username" not in _columns(c, "shop"):
        c.execute("ALTER TABLE shop ADD COLUMN owner_username TEXT")
    # Администратор может заблокировать аккаунт; видно время последнего входа
    if "user" in tables and "is_blocked" not in _columns(c, "user"):
        c.execute("ALTER TABLE user ADD COLUMN is_blocked INTEGER NOT NULL DEFAULT 0")
    if "user" in tables and "last_login" not in _columns(c, "user"):
        c.execute("ALTER TABLE user ADD COLUMN last_login TEXT")
    # Оплата сервиса Дәптер: реквизиты Kaspi и ставка вписываются в «Настройках»
    for col, typ in (("service_kaspi", "TEXT NOT NULL DEFAULT ''"), ("service_name", "TEXT NOT NULL DEFAULT ''"),
                     ("service_rate", "REAL NOT NULL DEFAULT 0.01")):
        if "shop" in tables and col not in _columns(c, "shop"):
            c.execute(f"ALTER TABLE shop ADD COLUMN {col} {typ}")
    if "customer" in tables and "tg_username" not in _columns(c, "customer"):
        c.execute("ALTER TABLE customer ADD COLUMN tg_username TEXT")
    # Демо-магазин общий для всех — уведомления из него не должны уходить ничьему Telegram
    if "shop" in tables and "user" in tables:
        c.execute("UPDATE shop SET owner_chat = NULL, owner_username = NULL WHERE user_id IN (SELECT id FROM user WHERE email = ?)", (DEMO_EMAIL,))
    c.execute("PRAGMA foreign_keys = ON")


def seed_demo_account(c):
    """Демо-аккаунт создаётся один раз. Если остались данные старой версии — они и становятся демо-магазином."""
    if c.execute("SELECT 1 FROM user WHERE email = ?", (DEMO_EMAIL,)).fetchone():
        return
    uid = c.execute("INSERT INTO user (email, full_name, phone, pw_hash) VALUES (?, ?, ?, ?)",
                    (DEMO_EMAIL, *DEMO_USER, hash_password(DEMO_PASSWORD))).lastrowid
    shop = c.execute("SELECT id FROM shop WHERE user_id IS NULL ORDER BY id LIMIT 1").fetchone()
    if shop:
        c.execute("UPDATE shop SET user_id = ? WHERE id = ?", (uid, shop["id"]))
        c.execute("UPDATE shop SET owner_secret = ? WHERE id = ? AND owner_secret IS NULL", (secrets.token_urlsafe(9), shop["id"]))
        return
    sid = create_shop(c, uid, "Береке")
    c.executemany("INSERT INTO product (shop_id, name, synonyms, price, unit) VALUES (?, ?, ?, ?, ?)",
                  [(sid, *p) for p in DEMO_PRODUCTS])
    c.executemany("INSERT INTO customer (shop_id, name, phone, address, language) VALUES (?, ?, ?, ?, ?)",
                  [(sid, *cu) for cu in DEMO_CUSTOMERS])


def ensure_admin(c):
    """Единственный администратор из ADMIN_EMAIL / ADMIN_PASSWORD. Магазина у него нет."""
    from .config import ADMIN_EMAIL, ADMIN_PASSWORD
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        return
    row = c.execute("SELECT id, pw_hash FROM user WHERE email = ?", (ADMIN_EMAIL,)).fetchone()
    if not row:
        c.execute("INSERT INTO user (email, full_name, phone, pw_hash) VALUES (?, 'Администратор', '', ?)",
                  (ADMIN_EMAIL, hash_password(ADMIN_PASSWORD)))
    elif not verify_password(ADMIN_PASSWORD, row["pw_hash"]):  # пароль сменили в настройках сервера
        c.execute("UPDATE user SET pw_hash = ? WHERE id = ?", (hash_password(ADMIN_PASSWORD), row["id"]))


def wipe_user(c, user_id: int) -> None:
    """Удалить аккаунт и все данные его магазина."""
    shop = c.execute("SELECT id FROM shop WHERE user_id = ?", (user_id,)).fetchone()
    if shop:
        sid = shop["id"]
        c.execute("DELETE FROM sale_item WHERE sale_id IN (SELECT id FROM sale WHERE shop_id = ?)", (sid,))
        c.execute("DELETE FROM product_photo WHERE product_id IN (SELECT id FROM product WHERE shop_id = ?)", (sid,))
        for table in ("reminder", "payment", "sale", "customer", "product"):
            c.execute(f"DELETE FROM {table} WHERE shop_id = ?", (sid,))
        c.execute("DELETE FROM shop WHERE id = ?", (sid,))
    c.execute("DELETE FROM auth_session WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM login_token WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM user WHERE id = ?", (user_id,))


def init_db() -> None:
    with session() as c:
        migrate(c)
        c.executescript(SCHEMA)
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS sale_client_ref ON sale (shop_id, client_ref) WHERE client_ref IS NOT NULL")
        seed_demo_account(c)
        ensure_admin(c)
        # Фото из старой папки data/photos переносим в базу (один раз)
        folder = DB_PATH.parent / "photos"
        if not TURSO_URL and folder.is_dir():
            for f in folder.glob("*.jpg"):
                pid = int(f.stem) if f.stem.isdigit() else None
                has_product = pid and c.execute("SELECT 1 FROM product WHERE id = ?", (pid,)).fetchone()
                if has_product and not c.execute("SELECT 1 FROM product_photo WHERE product_id = ?", (pid,)).fetchone():
                    c.execute("INSERT INTO product_photo (product_id, data) VALUES (?, ?)", (pid, f.read_bytes()))
        # Приводим статусы долгов в порядок (оплаты гасят самые старые)
        for (cid,) in c.execute("SELECT id FROM customer").fetchall():
            settle_fifo(c, cid)
        c.execute("DELETE FROM auth_session WHERE expires_at < datetime('now', 'localtime')")
        c.execute("DELETE FROM login_token WHERE expires_at < datetime('now', 'localtime')")
