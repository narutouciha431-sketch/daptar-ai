"""Сервер Дәптер AI: аккаунты, REST API, живая синхронизация экранов и раздача веб-приложения.

Каждый запрос к данным требует входа и работает только с магазином вошедшего пользователя.
"""
import asyncio
import base64
import logging
import binascii
import io
import re
from html import escape as html_escape
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import qrcode
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from qrcode.image.svg import SvgPathImage

from . import ai, bot
from .analytics import analytics, clear_demo, reset_demo, seed_demo
from .auth import (COOKIE, Me, check_password, clean_email, clean_phone, client_ip, current, drop_session, guard_login,
                   login_failed, new_login_token, new_session, resolve, set_cookie, use_login_token, ws_user)
from .config import BOT_USERNAME, SERVICE_KASPI, SERVICE_KASPI_NAME, WEBHOOK_SECRET
from .db import (BALANCE_SQL, DEMO_EMAIL, create_shop, get_shop, hash_password, init_db, open_debts, session,
                 settle_fifo, verify_password)
from .live import hub
from .parser import match_customer, parse
from .reports import daily_report, report_text
from .texts import plain

# Windows пишет ConnectionResetError, когда браузер закрывает вкладку, — это не ошибка сайта, прячем шум
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


async def evening_report_loop():
    """Раз в минуту проверяем, не пора ли отправить владельцам вечерний отчёт."""
    while True:
        await asyncio.sleep(60)
        try:
            today, now = date.today().isoformat(), datetime.now().strftime("%H:%M")
            with session() as c:
                shops = [dict(r) for r in c.execute(
                    "SELECT id, report_time FROM shop WHERE owner_chat IS NOT NULL AND (report_sent_on IS NULL OR report_sent_on != ?)",
                    (today,))]
            for s in shops:
                if now >= s["report_time"]:
                    # Отмечаем день даже при неудаче (бот заблокирован): не стучимся в Telegram каждую минуту
                    with session() as c:
                        c.execute("UPDATE shop SET report_sent_on = ? WHERE id = ?", (today, s["id"]))
                    await bot.send_report(s["id"])
        except Exception:
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    # Новый пустой сервер: демо-магазин сразу с историей, чтобы жюри было что посмотреть
    with session() as c:
        demo = c.execute("SELECT shop.id FROM shop JOIN user ON user.id = shop.user_id WHERE email = ?", (DEMO_EMAIL,)).fetchone()
        empty = demo and not c.execute("SELECT 1 FROM sale WHERE shop_id = ? LIMIT 1", (demo["id"],)).fetchone()
    if empty:
        reset_demo(demo["id"])
    await bot.start()
    task = asyncio.create_task(evening_report_loop())
    yield
    task.cancel()
    await bot.stop()


app = FastAPI(title="Дәптер AI", lifespan=lifespan)


def owned(c: sqlite3.Connection, table: str, row_id: int, shop_id: int) -> sqlite3.Row:
    """Запись должна принадлежать магазину пользователя — иначе 404, чужие данные не видны."""
    row = c.execute(f"SELECT * FROM {table} WHERE id = ? AND shop_id = ?", (row_id, shop_id)).fetchone()
    if not row:
        raise HTTPException(404, {"product": "Товар не найден", "customer": "Покупатель не найден"}.get(table, "Запись не найдена"))
    return row


@app.post("/tg/webhook")
async def telegram_webhook(request: Request):
    """Сообщения от Telegram на сервере. Чужие запросы без секрета отклоняем."""
    if not WEBHOOK_SECRET or request.headers.get("x-telegram-bot-api-secret-token") != WEBHOOK_SECRET:
        raise HTTPException(403)
    await bot.handle_webhook(await request.json())
    return {"ok": True}


@app.get("/healthz")
def healthz():
    """Для «будильника» и проверки Render: сервер жив."""
    return {"ok": True}


# ---------- аккаунты ----------
class RegisterIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=100)
    email: str = Field(min_length=5, max_length=120)
    phone: str = Field(min_length=1, max_length=25)
    shop_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class ProfileIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=100)
    phone: str = Field(min_length=1, max_length=25)


def login_response(request: Request, user_id: int) -> JSONResponse:
    resp = JSONResponse({"ok": True})
    set_cookie(resp, request, new_session(user_id))
    return resp


@app.post("/api/auth/register")
def register(r: RegisterIn, request: Request):
    email, phone = clean_email(r.email), clean_phone(r.phone)
    if len(r.full_name.split()) < 2:
        raise HTTPException(400, "Укажите фамилию и имя полностью")
    check_password(r.password)
    try:
        with session() as c:
            uid = c.execute("INSERT INTO user (email, full_name, phone, pw_hash) VALUES (?, ?, ?, ?)",
                            (email, r.full_name.strip(), phone, hash_password(r.password))).lastrowid
            create_shop(c, uid, r.shop_name.strip())
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Этот email уже зарегистрирован. Войдите или используйте другой.")
    return login_response(request, uid)


@app.post("/api/auth/login")
def login(r: LoginIn, request: Request):
    email = r.email.strip().lower()
    key = f"{email}|{client_ip(request)}"
    guard_login(key)
    with session() as c:
        u = c.execute("SELECT id, pw_hash FROM user WHERE email = ?", (email,)).fetchone()
    if not u or not verify_password(r.password, u["pw_hash"]):
        login_failed(key)
        raise HTTPException(401, "Неверный email или пароль")
    return login_response(request, u["id"])


@app.post("/api/auth/demo")
def login_demo(request: Request):
    """Кнопка «Посмотреть демо» — вход в демо-магазин без ввода пароля."""
    with session() as c:
        u = c.execute("SELECT id FROM user WHERE email = ?", (DEMO_EMAIL,)).fetchone()
    if not u:
        raise HTTPException(404, "Демо-аккаунт не найден")
    return login_response(request, u["id"])


@app.post("/api/auth/logout")
def logout(request: Request):
    drop_session(request.cookies.get(COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@app.get("/api/auth/state")
def auth_state(request: Request):
    """Вошёл ли пользователь — без ошибки 401 в консоли на открытых страницах."""
    return {"logged": logged_in(request)}


@app.get("/api/auth/me")
def me(m: Me = Depends(current)):
    with session() as c:
        u = dict(c.execute("SELECT id, email, full_name, phone, created_at FROM user WHERE id = ?", (m.user_id,)).fetchone())
    u["is_demo"] = u["email"] == DEMO_EMAIL
    return u


@app.put("/api/auth/profile")
def profile_update(p: ProfileIn, m: Me = Depends(current)):
    if len(p.full_name.split()) < 2:
        raise HTTPException(400, "Укажите фамилию и имя полностью")
    with session() as c:
        c.execute("UPDATE user SET full_name = ?, phone = ? WHERE id = ?", (p.full_name.strip(), clean_phone(p.phone), m.user_id))
    return me(m)


# ---------- живая синхронизация (телефон сканирует — ноутбук видит сразу) ----------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    m = ws_user(ws)
    if not m:
        # Принимаем и сразу закрываем с кодом 4401 — страница поймёт, что нужно войти
        await ws.accept()
        await ws.close(code=4401)
        return
    await hub.join(ws, m.shop_id)
    token = ws.cookies.get(COOKIE)
    try:
        while True:
            msg = await ws.receive_json()
            if not resolve(token):  # вышли из аккаунта — экран больше не участвует в работе магазина
                await ws.close(code=4401)
                break
            # Сообщения от экранов этого магазина пересылаем остальным его экранам
            await hub.broadcast(m.shop_id, msg)
    except (WebSocketDisconnect, ValueError, RuntimeError):
        pass
    finally:
        hub.leave(ws, m.shop_id)


# ---------- товары ----------
class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    synonyms: str = Field("", max_length=500)
    price: int = Field(ge=0, le=100_000_000)
    unit: str = "шт"
    barcode: str | None = None


def _clean(p: ProductIn) -> tuple:
    barcode = (p.barcode or "").strip() or None
    synonyms = ", ".join(s.strip() for s in p.synonyms.split(",") if s.strip())
    return p.name.strip(), synonyms, p.price, p.unit.strip() or "шт", barcode


@app.get("/api/products")
def list_products(q: str = "", m: Me = Depends(current)):
    with session() as c:
        like = f"%{q.strip().lower()}%"
        rows = c.execute(
            "SELECT * FROM product WHERE shop_id = ? AND (lower(name) LIKE ? OR lower(synonyms) LIKE ? OR barcode LIKE ?) ORDER BY name",
            (m.shop_id, like, like, like),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/products/barcode/{code}")
def product_by_barcode(code: str, m: Me = Depends(current)):
    with session() as c:
        row = c.execute("SELECT * FROM product WHERE shop_id = ? AND barcode = ?", (m.shop_id, code.strip())).fetchone()
    if not row:
        raise HTTPException(404, "Товар с таким штрихкодом не найден")
    return dict(row)


@app.post("/api/products", status_code=201)
async def create_product(p: ProductIn, m: Me = Depends(current)):
    try:
        with session() as c:
            pid = c.execute("INSERT INTO product (shop_id, name, synonyms, price, unit, barcode) VALUES (?, ?, ?, ?, ?, ?)",
                            (m.shop_id, *_clean(p))).lastrowid
            row = c.execute("SELECT * FROM product WHERE id = ?", (pid,)).fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Этот штрихкод уже привязан к другому товару")
    await hub.broadcast(m.shop_id, {"type": "products_changed"})
    return dict(row)


@app.put("/api/products/{pid}")
async def update_product(pid: int, p: ProductIn, m: Me = Depends(current)):
    try:
        with session() as c:
            owned(c, "product", pid, m.shop_id)
            c.execute("UPDATE product SET name = ?, synonyms = ?, price = ?, unit = ?, barcode = ? WHERE id = ?", (*_clean(p), pid))
            row = c.execute("SELECT * FROM product WHERE id = ?", (pid,)).fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Этот штрихкод уже привязан к другому товару")
    await hub.broadcast(m.shop_id, {"type": "products_changed"})
    return dict(row)


@app.delete("/api/products/{pid}", status_code=204)
async def delete_product(pid: int, m: Me = Depends(current)):
    with session() as c:
        owned(c, "product", pid, m.shop_id)
        c.execute("UPDATE sale_item SET product_id = NULL WHERE product_id = ?", (pid,))  # история продаж остаётся
        c.execute("DELETE FROM product_photo WHERE product_id = ?", (pid,))
        c.execute("DELETE FROM product WHERE id = ?", (pid,))
    await hub.broadcast(m.shop_id, {"type": "products_changed"})


# ---------- покупатели ----------
class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    phone: str = ""
    address: str = ""
    note: str = ""
    language: str = Field("kk", pattern="^(kk|ru)$")


def customers_with_balance(c, shop_id: int, where: str = "", args: tuple = ()):
    return c.execute(
        f"SELECT customer.*, ({BALANCE_SQL}) AS balance, "
        "(SELECT MAX(s.created_at) FROM sale s WHERE s.customer_id = customer.id) AS last_sale "
        f"FROM customer WHERE shop_id = ? {('AND ' + where) if where else ''} ORDER BY balance DESC, name",
        (shop_id, *args),
    ).fetchall()


@app.get("/api/customers")
def list_customers(q: str = "", m: Me = Depends(current)):
    with session() as c:
        like = f"%{q.strip().lower()}%"
        rows = customers_with_balance(c, m.shop_id, "(lower(name) LIKE ? OR phone LIKE ?)", (like, like))
    return [dict(r) for r in rows]


@app.get("/api/customers/{cid}")
def get_customer(cid: int, m: Me = Depends(current)):
    with session() as c:
        row = customers_with_balance(c, m.shop_id, "id = ?", (cid,))
        if not row:
            raise HTTPException(404, "Покупатель не найден")
        sales = c.execute("SELECT * FROM sale WHERE customer_id = ? ORDER BY created_at DESC, id DESC", (cid,)).fetchall()
        items = {}
        for it in c.execute("SELECT si.* FROM sale_item si JOIN sale s ON s.id = si.sale_id WHERE s.customer_id = ?", (cid,)):
            items.setdefault(it["sale_id"], []).append(dict(it))
        payments = c.execute("SELECT * FROM payment WHERE customer_id = ? ORDER BY created_at DESC, id DESC", (cid,)).fetchall()
    return {
        **dict(row[0]),
        "sales": [{**dict(s), "items": items.get(s["id"], [])} for s in sales],
        "payments": [dict(p) for p in payments],
    }


@app.post("/api/customers", status_code=201)
async def create_customer(cu: CustomerIn, m: Me = Depends(current)):
    with session() as c:
        cid = c.execute("INSERT INTO customer (shop_id, name, phone, address, note, language) VALUES (?, ?, ?, ?, ?, ?)",
                        (m.shop_id, cu.name.strip(), cu.phone.strip(), cu.address.strip(), cu.note.strip(), cu.language)).lastrowid
        row = customers_with_balance(c, m.shop_id, "id = ?", (cid,))[0]
    await hub.broadcast(m.shop_id, {"type": "customers_changed"})
    return dict(row)


@app.put("/api/customers/{cid}")
async def update_customer(cid: int, cu: CustomerIn, m: Me = Depends(current)):
    with session() as c:
        owned(c, "customer", cid, m.shop_id)
        c.execute("UPDATE customer SET name = ?, phone = ?, address = ?, note = ?, language = ? WHERE id = ?",
                  (cu.name.strip(), cu.phone.strip(), cu.address.strip(), cu.note.strip(), cu.language, cid))
        row = customers_with_balance(c, m.shop_id, "id = ?", (cid,))[0]
    await hub.broadcast(m.shop_id, {"type": "customers_changed"})
    return dict(row)


@app.delete("/api/customers/{cid}")
async def delete_customer(cid: int, m: Me = Depends(current)):
    """Удалить покупателя вместе с его покупками, долгами, возвратами и напоминаниями (только своего магазина)."""
    with session() as c:
        owned(c, "customer", cid, m.shop_id)
        c.execute("DELETE FROM sale_item WHERE sale_id IN (SELECT id FROM sale WHERE customer_id = ?)", (cid,))
        for table in ("sale", "payment", "reminder"):
            c.execute(f"DELETE FROM {table} WHERE customer_id = ?", (cid,))
        c.execute("DELETE FROM customer WHERE id = ? AND shop_id = ?", (cid, m.shop_id))
    await hub.broadcast(m.shop_id, {"type": "customers_changed"})
    return {"deleted": cid}


# ---------- разбор фразы ----------
class ParseIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@app.post("/api/parse")
async def parse_text(body: ParseIn, m: Me = Depends(current)):
    """Сначала быстрые правила; если они поняли не всё — спрашиваем ИИ."""
    with session() as c:
        products = [dict(r) for r in c.execute("SELECT * FROM product WHERE shop_id = ?", (m.shop_id,))]
        customers = [dict(r) for r in c.execute("SELECT id, name FROM customer WHERE shop_id = ?", (m.shop_id,))]
    result = parse(body.text, products, customers)
    result["ai"] = False
    # «екі бес жү» — распознавание потеряло «мың»: такие оплаты тоже отдаём ИИ
    unclear = (result["intent"] == "sale" and (result["unknown"] or not result["items"])) or \
              (result["intent"] == "payment" and result["unknown"])
    if unclear and ai.enabled() and products:
        ai_result = await ai.parse_phrase(body.text, products, customers)
        if ai_result:
            merged = merge_ai(result, ai_result, products, customers)
            if merged:
                return merged
    return result


def merge_ai(rules: dict, a: dict, products: list[dict], customers: list[dict]) -> dict | None:
    """Переводит ответ ИИ в формат правил. Принимаем, только если ИИ понял больше."""
    by_name = {p["name"].lower(): p for p in products}
    items = []
    for it in a.get("items", []):
        p = by_name.get(str(it.get("product", "")).lower())
        if p and it.get("qty", 0) > 0:
            q = it["qty"]
            items.append({"product_id": p["id"], "name": p["name"], "qty": q, "price": p["price"], "amount": round(q * p["price"])})
    intent = a.get("intent", "sale")
    if intent == "sale" and len(items) <= len(rules["items"]) and not (a.get("customer") and not rules["customer"] and not rules["new_customer_name"]):
        return None
    out = {**rules, "items": items or rules["items"], "intent": intent, "ai": True, "unknown": []}
    out["kind"] = {"debt": "debt", "paid": "paid"}.get(a.get("kind")) or rules["kind"]
    out["half_paid"] = bool(a.get("half_paid")) or rules["half_paid"]
    if intent == "payment":
        out["amount"] = int(a.get("amount") or 0) or rules["amount"]
    name = (a.get("customer") or "").strip()
    if name and not rules["customer"]:
        cust, _ = match_customer(name.lower().split(), customers)
        if cust:
            out["customer"], out["new_customer_name"] = {"id": cust["id"], "name": cust["name"]}, None
        else:
            out["new_customer_name"] = name
    return out


# ---------- продажи и долги ----------
class ItemIn(BaseModel):
    product_id: int | None = None
    name: str = Field(min_length=1)
    qty: float = Field(gt=0, le=100_000)
    price: int = Field(ge=0, le=100_000_000)


class SaleIn(BaseModel):
    kind: str = Field(pattern="^(paid|debt)$")
    items: list[ItemIn] = Field(min_length=1)
    customer_id: int | None = None
    new_customer_name: str | None = None
    paid_now: int = Field(0, ge=0)
    due_days: int = Field(14, ge=1, le=365)
    source: str = Field("text", pattern="^(text|voice|barcode|photo)$")
    raw_text: str = Field("", max_length=500)
    client_ref: str | None = Field(None, max_length=64)  # номер операции от кассы


@app.post("/api/sales", status_code=201)
async def create_sale(s: SaleIn, m: Me = Depends(current)):
    total = sum(round(it.qty * it.price) for it in s.items)
    with session() as c:
        if s.client_ref:
            dup = c.execute("SELECT * FROM sale WHERE shop_id = ? AND client_ref = ?", (m.shop_id, s.client_ref)).fetchone()
            if dup:  # двойное нажатие или повтор после обрыва сети — возвращаем уже созданную запись
                sale = dict(dup)
                if sale["kind"] == "debt":
                    sale["consent_sent"], sale["consent_link"] = False, bot.deep_link("d_" + sale["consent_token"])
                return sale
        customer_id = s.customer_id
        name = (s.new_customer_name or "").strip()
        if not customer_id and name:
            # Новый покупатель — и для долга, и для обычной покупки (чтобы сохранилась его история)
            customer_id = c.execute("INSERT INTO customer (shop_id, name) VALUES (?, ?)", (m.shop_id, name)).lastrowid
        if s.kind == "debt" and not customer_id:
            raise HTTPException(400, "Для долга нужно выбрать покупателя")
        if customer_id:
            owned(c, "customer", customer_id, m.shop_id)
        if s.kind == "debt":
            paid_now = min(s.paid_now, total)
            status, due = "pending", (date.today() + timedelta(days=s.due_days)).isoformat()
            token = secrets.token_urlsafe(8)
        else:
            paid_now, status, due, token = total, "paid", None, None
        sid = c.execute(
            "INSERT INTO sale (shop_id, customer_id, kind, total, paid_now, due_date, status, consent_token, source, raw_text, client_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (m.shop_id, customer_id, s.kind, total, paid_now, due, status, token, s.source, s.raw_text, s.client_ref),
        ).lastrowid
        # product_id берём только из своего прайса
        own = {r["id"] for r in c.execute("SELECT id FROM product WHERE shop_id = ?", (m.shop_id,))}
        c.executemany(
            "INSERT INTO sale_item (sale_id, product_id, name, qty, price, amount) VALUES (?, ?, ?, ?, ?, ?)",
            [(sid, it.product_id if it.product_id in own else None, it.name, it.qty, it.price, round(it.qty * it.price)) for it in s.items],
        )
        sale = dict(c.execute("SELECT * FROM sale WHERE id = ?", (sid,)).fetchone())
    await hub.broadcast(m.shop_id, {"type": "sale_created", "sale_id": sid})
    if s.kind == "debt":
        # Если покупатель уже подключён к боту, запрос на подтверждение уходит сразу
        sale["consent_sent"] = await bot.send_consent_request(sid)
        sale["consent_link"] = bot.deep_link("d_" + sale["consent_token"])
    return sale


@app.get("/api/sales/{sid}/qr.svg")
def sale_qr(sid: int, m: Me = Depends(current)):
    """QR-код согласия на долг: покупатель сканирует его телефоном и открывает бота."""
    with session() as c:
        row = owned(c, "sale", sid, m.shop_id)
    if not row["consent_token"]:
        raise HTTPException(404, "Это не долг")
    return qr_svg(bot.deep_link("d_" + row["consent_token"]))


def qr_svg(data: str) -> Response:
    """QR в SVG: не требует Pillow, чётко масштабируется на любом экране."""
    img = qrcode.make(data, image_factory=SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.get("/api/sales")
def recent_sales(limit: int = 20, m: Me = Depends(current)):
    with session() as c:
        rows = c.execute(
            "SELECT s.*, cu.name AS customer_name, "
            "(SELECT group_concat(si.name || ' ×' || (CASE WHEN si.qty = CAST(si.qty AS INTEGER) THEN CAST(si.qty AS INTEGER) "
            "ELSE si.qty END), ', ') FROM sale_item si WHERE si.sale_id = s.id) AS items_text "
            "FROM sale s LEFT JOIN customer cu ON cu.id = s.customer_id WHERE s.shop_id = ? ORDER BY s.id DESC LIMIT ?",
            (m.shop_id, max(1, min(limit, 200))),
        ).fetchall()
    return [dict(r) for r in rows]


class PaymentIn(BaseModel):
    customer_id: int
    amount: int = Field(gt=0, le=10_000_000_000)
    method: str = Field("cash", pattern="^(cash|kaspi)$")


@app.post("/api/payments", status_code=201)
async def create_payment(p: PaymentIn, m: Me = Depends(current)):
    with session() as c:
        row = customers_with_balance(c, m.shop_id, "id = ?", (p.customer_id,))
        if not row:
            raise HTTPException(404, "Покупатель не найден")
        balance = row[0]["balance"]
        if balance <= 0:
            raise HTTPException(400, "У покупателя нет долга")
        amount = min(p.amount, balance)
        c.execute("INSERT INTO payment (shop_id, customer_id, amount, method) VALUES (?, ?, ?, ?)",
                  (m.shop_id, p.customer_id, amount, p.method))
        # Оплата гасит самые старые долги; полностью покрытые закрываем
        settle_fifo(c, p.customer_id)
    await hub.broadcast(m.shop_id, {"type": "payment_created", "customer_id": p.customer_id})
    return {"accepted": amount, "balance": balance - amount}


# ---------- долги и напоминания ----------
@app.get("/api/debts")
def list_debts(m: Me = Depends(current)):
    """Покупатели с долгом: сумма, ближайший срок, статусы подтверждения, подключён ли бот."""
    today = date.today().isoformat()
    with session() as c:
        rows = c.execute(
            f"SELECT customer.id, name, phone, language, tg_chat_id IS NOT NULL AS in_bot, ({BALANCE_SQL}) AS balance, "
            "(SELECT MIN(due_date) FROM sale s WHERE s.customer_id = customer.id AND s.kind = 'debt' AND s.status IN ('pending','confirmed')) AS due, "
            "(SELECT COUNT(*) FROM sale s WHERE s.customer_id = customer.id AND s.kind = 'debt' AND s.status = 'pending') AS pending, "
            "(SELECT COUNT(*) FROM sale s WHERE s.customer_id = customer.id AND s.kind = 'debt' AND s.status = 'confirmed') AS confirmed, "
            "(SELECT MAX(sent_at) FROM reminder r WHERE r.customer_id = customer.id AND r.status = 'sent') AS last_reminder, tg_username "
            "FROM customer WHERE shop_id = ? AND balance > 0 ORDER BY due IS NULL, due, balance DESC", (m.shop_id,)
        ).fetchall()
        result = []
        for r in rows:
            sales = open_debts(c, r["id"])
            for s in sales:
                s["debt"] = s["left"]  # показываем остаток с учётом частичных возвратов
                s["items"] = c.execute("SELECT group_concat(name, ', ') FROM sale_item WHERE sale_id = ?", (s["id"],)).fetchone()[0]
            result.append({**dict(r), "overdue": bool(r["due"] and r["due"] < today), "sales": sales[::-1]})
    return result


def whatsapp_link(phone: str, text: str) -> str | None:
    """Ссылка «написать в WhatsApp» с готовым текстом — без платного API, отправляет сам владелец."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return f"https://wa.me/{digits}?text={quote(text)}" if len(digits) == 11 else None


@app.get("/api/reminders/{cid}")
def reminder_preview(cid: int, m: Me = Depends(current)):
    with session() as c:
        owned(c, "customer", cid, m.shop_id)
    info = bot.reminder_text(cid)
    info["whatsapp"] = whatsapp_link(info["phone"], plain(info["text"]))
    info["plain"] = plain(info["text"])
    return info


class ReminderIn(BaseModel):
    text: str = Field(min_length=5, max_length=1500)
    channel: str = Field("telegram", pattern="^(telegram|whatsapp|copy)$")


@app.post("/api/reminders/{cid}")
async def reminder_send(cid: int, r: ReminderIn, m: Me = Depends(current)):
    with session() as c:
        owned(c, "customer", cid, m.shop_id)
    if r.channel == "telegram":
        try:
            sent = await bot.send_reminder(cid, r.text)
        except Exception as e:
            raise HTTPException(502, f"Telegram не отправил сообщение: {e}")
        if not sent:
            raise HTTPException(400, "Покупатель ещё не подключён к боту. Отправьте через WhatsApp.")
    with session() as c:
        c.execute("INSERT INTO reminder (shop_id, customer_id, text, status, sent_at) VALUES (?, ?, ?, 'sent', datetime('now','localtime'))",
                  (m.shop_id, cid, r.text))
    await hub.broadcast(m.shop_id, {"type": "reminder_sent", "customer_id": cid})
    return {"sent": True, "channel": r.channel}


# ---------- магазин и отчёт ----------
class ShopIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    district: str = Field(min_length=1, max_length=80)
    tax_rate: float = Field(ge=0, le=0.2)
    kaspi_link: str = Field("", max_length=300)
    language: str = Field("kk", pattern="^(kk|ru)$")
    report_time: str = Field("21:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    service_kaspi: str = Field("", max_length=40)
    service_name: str = Field("", max_length=80)
    service_rate: float = Field(0.01, ge=0.005, le=0.02)


@app.get("/api/shop")
def shop_info(m: Me = Depends(current)):
    with session() as c:
        shop = get_shop(c, m.shop_id)
    shop["bot_enabled"] = bot.enabled()
    shop["ai_enabled"] = ai.enabled()
    shop["bot_username"] = BOT_USERNAME
    shop["owner_linked"] = bool(shop["owner_chat"])
    shop.pop("owner_chat")
    with session() as c:
        shop["is_demo"] = bool(c.execute("SELECT 1 FROM user WHERE id = ? AND email = ?", (m.user_id, DEMO_EMAIL)).fetchone())
    shop["owner_link"] = bot.deep_link("owner_" + shop["owner_secret"])
    shop.pop("owner_secret")
    return shop


@app.put("/api/shop")
async def shop_update(s: ShopIn, m: Me = Depends(current)):
    with session() as c:
        c.execute("UPDATE shop SET name = ?, district = ?, tax_rate = ?, kaspi_link = ?, language = ?, report_time = ?, "
                  "service_kaspi = ?, service_name = ?, service_rate = ? WHERE id = ?",
                  (s.name.strip(), s.district.strip(), s.tax_rate, s.kaspi_link.strip(), s.language, s.report_time,
                   s.service_kaspi.strip(), s.service_name.strip(), s.service_rate, m.shop_id))
    await hub.broadcast(m.shop_id, {"type": "shop_changed"})
    return shop_info(m)


@app.get("/api/shop/owner-qr.svg")
def owner_qr(m: Me = Depends(current)):
    with session() as c:
        secret = get_shop(c, m.shop_id)["owner_secret"]
    return qr_svg(bot.deep_link("owner_" + secret))


@app.get("/api/report")
def report_today(m: Me = Depends(current)):
    r = daily_report(m.shop_id)
    r["text"] = plain(report_text(r))
    return r


@app.post("/api/shop/owner-unlink")
async def owner_unlink(m: Me = Depends(current)):
    """Отвязать Telegram владельца: уведомления больше никуда не уходят, пока не подключат заново."""
    with session() as c:
        c.execute("UPDATE shop SET owner_chat = NULL, owner_username = NULL WHERE id = ?", (m.shop_id,))
    await hub.broadcast(m.shop_id, {"type": "owner_linked"})
    return {"ok": True}


def tenge(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₸"


@app.post("/api/service/send")
async def service_send(m: Me = Depends(current)):
    """Счёт за сервис Дәптер за текущий месяц — в Telegram владельца, с реквизитами Kaspi."""
    with session() as c:
        shop = get_shop(c, m.shop_id)
    kaspi = shop.get("service_kaspi") or SERVICE_KASPI
    name = shop.get("service_name") or SERVICE_KASPI_NAME
    if not kaspi:
        raise HTTPException(400, "Впишите номер Kaspi для оплаты сервиса: Настройки → Оплата сервиса Дәптер.")
    r = daily_report(m.shop_id)
    text = (f"🧾 <b>Оплата сервиса Дәптер AI</b>\nМесяц: {r['service_month']}\n"
            f"Оплаченные продажи: {tenge(r['service_paid'])}\nВозвращённые долги: {tenge(r['service_back'])}\n"
            f"Ставка: {r['service_rate'] * 100:g}%\n<b>К оплате: {tenge(r['service_fee'])}</b>\n\n"
            f"Переведите на Kaspi: <b>{html_escape(kaspi)}</b>"
            + (f"\nПолучатель: {html_escape(name)}" if name else ""))
    if not await bot.notify_owner(m.shop_id, text):
        raise HTTPException(400, "Telegram владельца не подключён: Настройки → Telegram-бот.")
    return {"sent": True}


@app.post("/api/report/send")
async def report_send(m: Me = Depends(current)):
    if not await bot.send_report(m.shop_id):
        raise HTTPException(400, "Владелец ещё не подключён к боту (Настройки → подключить владельца)")
    return {"sent": True}


# ---------- ИИ: фото товара и советы ----------
class PhotoIn(BaseModel):
    image: str = Field(min_length=100, max_length=4_000_000)  # data:image/jpeg;base64,...


def split_data_url(data_url: str) -> tuple[str, str]:
    m = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)", data_url.strip())
    if not m:
        raise HTTPException(400, "Нужна картинка JPEG, PNG или WEBP")
    return m.group(1), m.group(2)


def decode_image(b64: str) -> bytes:
    try:
        return base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Фото пришло не полностью. Попробуйте ещё раз.")


@app.post("/api/ai/match")
async def ai_match(p: PhotoIn, m: Me = Depends(current)):
    """Фото товара на кассе → до 3 похожих товаров из прайса; продавец подтверждает нужный."""
    if not ai.enabled():
        raise HTTPException(400, "ИИ не подключён: нет ключа GEMINI_API_KEY в .env")
    mime, b64 = split_data_url(p.image)
    decode_image(b64)
    with session() as c:
        prods = [dict(r) for r in c.execute("SELECT id, name, synonyms, price, unit, photo AS has_photo "
                                            "FROM product WHERE shop_id = ? ORDER BY name LIMIT 600", (m.shop_id,))]
    if not prods:
        raise HTTPException(400, "Прайс пуст — сначала добавьте товары во вкладке «Товары».")
    r = await ai.match_photo(b64, mime, prods)
    if r is None:
        raise HTTPException(503, "ИИ сейчас не ответил. Попробуйте ещё раз.")
    by_id = {x["id"]: x for x in prods}
    out, seen_ids = [], set()
    for cand in r.get("candidates", []):
        pid = cand.get("id")
        if pid in by_id and pid not in seen_ids:
            seen_ids.add(pid)
            out.append({**by_id[pid], "confidence": round(float(cand.get("confidence") or 0), 2)})
    return {"seen": r.get("seen", ""), "candidates": out[:3]}


@app.post("/api/ai/photo")
async def ai_photo(p: PhotoIn, m: Me = Depends(current)):
    """Фото ценника или упаковки → название, цена, синонимы (Gemini)."""
    if not ai.enabled():
        raise HTTPException(400, "ИИ не подключён: нет ключа GEMINI_API_KEY в .env")
    mime, b64 = split_data_url(p.image)
    decode_image(b64)  # битый файл — понятная ошибка, а не запрос в ИИ
    r = await ai.read_photo(b64, mime)
    if not r:
        raise HTTPException(503, "ИИ сейчас не ответил. Попробуйте ещё раз или заполните вручную.")
    return r


@app.post("/api/products/{pid}/photo")
async def product_photo_upload(pid: int, p: PhotoIn, m: Me = Depends(current)):
    _, b64 = split_data_url(p.image)
    data = decode_image(b64)
    with session() as c:
        owned(c, "product", pid, m.shop_id)
        c.execute("INSERT OR REPLACE INTO product_photo (product_id, data) VALUES (?, ?)", (pid, data))
        c.execute("UPDATE product SET photo = 1 WHERE id = ?", (pid,))
    await hub.broadcast(m.shop_id, {"type": "products_changed"})
    return {"ok": True}


@app.get("/api/products/{pid}/photo")
def product_photo(pid: int, m: Me = Depends(current)):
    with session() as c:
        owned(c, "product", pid, m.shop_id)
        row = c.execute("SELECT data FROM product_photo WHERE product_id = ?", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, "Фото нет")
    return Response(bytes(row["data"]), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


_insights_cache: dict[int, dict] = {}
LABEL_RE = re.compile(r"П\d+")


def restore_names(text: str, names: dict) -> str:
    """Метки П1, П2… из ответа ИИ заменяем на настоящие имена покупателей."""
    return LABEL_RE.sub(lambda mm: names.get(mm.group(0), mm.group(0)), text)


def weekday_sales(series: list[dict]) -> dict:
    names = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    out = {n: 0 for n in names}
    for s in series:
        out[names[date.fromisoformat(s["day"]).weekday()]] += s["sold_paid"] + s["sold_debt"]
    return out


@app.get("/api/ai/insights")
async def ai_insights(refresh: bool = False, m: Me = Depends(current)):
    """Советы владельцу. В ИИ уходят только обезличенные цифры: без имён, телефонов и адресов."""
    if not ai.enabled():
        raise HTTPException(400, "ИИ не подключён: нет ключа GEMINI_API_KEY в .env")
    cached = _insights_cache.get(m.shop_id)
    if not refresh and cached and cached["at"] > datetime.now().timestamp() - 600:
        return cached["data"]
    a = analytics(m.shop_id, 30)
    if not any(s["count"] for s in a["series"]):
        raise HTTPException(400, "Пока мало данных для советов: запишите несколько продаж или долгов.")
    with session() as c:
        shop = get_shop(c, m.shop_id)
    stats = {
        "продажи_7_дней": a["week"], "продажи_прошлые_7_дней": a["prev_week"],
        "всего_должны": a["owed"], "доля_возвращённых_долгов_процент": a["return_rate"],
        "возраст_долгов_тенге": a["aging"],
        "долги_по_покупателям": [{"покупатель": f"П{i + 1}", "долг": d["balance"]} for i, d in enumerate(a["debtors"])],
        "топ_товаров": [{"товар": t["name"], "выручка": t["amount"], "штук": t["qty"]} for t in a["top_products"]],
        "продажи_по_дням_недели": weekday_sales(a["series"]),
    }
    tips = await ai.insights(stats, shop["language"])
    if not tips:
        raise HTTPException(503, "ИИ сейчас не ответил. Попробуйте через минуту.")
    # Имена в ИИ не уходили (метки П1, П2…) — подставляем их уже у себя
    names = {f"П{i + 1}": d["name"] for i, d in enumerate(a["debtors"])}
    tips = [{"title": restore_names(t["title"], names), "text": restore_names(t["text"], names)} for t in tips]
    data = {"tips": tips, "at": datetime.now().strftime("%H:%M")}
    _insights_cache[m.shop_id] = {"at": datetime.now().timestamp(), "data": data}
    return data


# ---------- кабинет: аналитика и демо-история ----------
@app.get("/api/analytics")
def analytics_view(days: int = 30, m: Me = Depends(current)):
    return analytics(m.shop_id, days)


@app.post("/api/demo/seed")
async def demo_seed(m: Me = Depends(current)):
    n = seed_demo(m.shop_id, 30)
    if not n:
        raise HTTPException(400, "Сначала добавьте хотя бы один товар и одного покупателя")
    await hub.broadcast(m.shop_id, {"type": "sale_created", "sale_id": None})
    return {"created": n}


@app.post("/api/demo/clear")
async def demo_clear(m: Me = Depends(current)):
    n = clear_demo(m.shop_id)
    await hub.broadcast(m.shop_id, {"type": "sale_created", "sale_id": None})
    return {"deleted": n}


@app.post("/api/demo/reset")
async def demo_reset(m: Me = Depends(current)):
    """Только для общего демо-аккаунта: вернуть магазин «Береке» к исходному виду перед показом."""
    with session() as c:
        if not c.execute("SELECT 1 FROM user WHERE id = ? AND email = ?", (m.user_id, DEMO_EMAIL)).fetchone():
            raise HTTPException(403, "Сбросить можно только демо-магазин")
    n = reset_demo(m.shop_id)
    for t in ("products_changed", "customers_changed", "sale_created"):
        await hub.broadcast(m.shop_id, {"type": t, "sale_id": None})
    return {"created": n}


# ---------- сканер на телефоне ----------
TUNNEL_LOG = DATA_DIR / "tunnel.log"


LINK_FILE = DATA_DIR / "link.txt"  # сюда пишет адрес tools/run.py


def public_url(request: Request | None = None) -> str | None:
    """https-адрес для телефона. Лучше всего — тот, с которого открыта страница (он точно живой);
    иначе — из самого свежего файла: link.txt (run.py) или журнала cloudflared."""
    host = request.headers.get("host", "") if request is not None else ""
    if host and host.split(":")[0] not in ("127.0.0.1", "localhost", "[::1]", "0.0.0.0"):
        return "https://" + host
    files = sorted((f for f in (LINK_FILE, TUNNEL_LOG) if f.exists()), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files:
        found = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", f.read_text(encoding="utf-8", errors="ignore"))
        if found:
            return found[-1]
    return None


def scanner_link(user_id: int, request: Request, mode: str = "cart") -> str | None:
    """Ссылка для телефона: ключ входа (15 минут) сразу открывает сканер этого магазина в нужном режиме."""
    url = public_url(request)
    return f"{url}/scan/k/{new_login_token(user_id)}?mode={mode}" if url else None


@app.get("/api/scanner")
def scanner_info(request: Request, m: Me = Depends(current)):
    """Только «доступен ли сканер»: сам ключ входа выдаётся один раз — в QR-картинке."""
    base = public_url(request)
    return {"available": base is not None, "base": base}


@app.get("/api/scanner/qr.svg")
def scanner_qr(request: Request, mode: str = "cart", m: Me = Depends(current)):
    link = scanner_link(m.user_id, request, "price" if mode == "price" else "cart")
    if not link:
        raise HTTPException(404, "Туннель не запущен")
    return qr_svg(link)


@app.get("/scan/k/{token}")
def scan_login(token: str, request: Request, mode: str = "cart"):
    """Телефон открыл QR со сканера: входим одноразовым ключом и открываем сканер."""
    uid = use_login_token(token)
    if not uid:
        return RedirectResponse("/login?next=/scan&expired=1", status_code=303)
    resp = RedirectResponse("/scan?mode=" + ("price" if mode == "price" else "cart"), status_code=303)
    set_cookie(resp, request, new_session(uid))
    return resp


# ---------- страницы ----------
def logged_in(request: Request) -> bool:
    return resolve(request.cookies.get(COOKIE)) is not None


@app.get("/")
def landing():
    return FileResponse(WEB_DIR / "landing.html")


@app.get("/login")
def login_page():
    return FileResponse(WEB_DIR / "auth.html")


@app.get("/register")
def register_page():
    return FileResponse(WEB_DIR / "auth.html")


@app.get("/app")
def app_page(request: Request):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(WEB_DIR / "index.html")


@app.get("/scan")
def scan_page(request: Request):
    """Страница сканера штрихкодов для телефона."""
    if not logged_in(request):
        return RedirectResponse("/login?next=/scan", status_code=303)
    return FileResponse(WEB_DIR / "scan.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
