"""Аккаунты: регистрация, вход, сессии в cookie, одноразовый вход телефона-сканера."""
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException, Request, WebSocket

from .db import session

COOKIE = "daptar_session"
SESSION_DAYS = 30
EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")


@dataclass
class Me:
    user_id: int
    shop_id: int


# ---------- проверки ----------
def clean_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.fullmatch(email) or ".." in email:
        raise HTTPException(400, "Введите правильный email, например aigul@gmail.com")
    return email


def clean_phone(phone: str) -> str:
    """Казахстанский мобильный: +7 7XX XXX XX XX. Принимаем 8 7XX…, +77XX…, с пробелами и скобками."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) == 10 and digits[0] == "7":
        digits = "7" + digits
    if not (len(digits) == 11 and digits.startswith("77")):
        raise HTTPException(400, "Введите казахстанский номер, например +7 701 234 56 78")
    return f"+7 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:11]}"


def check_password(password: str):
    if len(password) < 8:
        raise HTTPException(400, "Пароль должен быть не короче 8 символов")
    if not (re.search(r"[A-Za-zА-Яа-яӘәҒғҚқҢңӨөҰұҮүҺһІі]", password) and re.search(r"\d", password)):
        raise HTTPException(400, "В пароле должны быть и буквы, и цифры")


# ---------- защита от перебора паролей ----------
_fails: dict[str, list[float]] = {}  # ключ: адрес устройства + email


def guard_login(key: str):
    recent = [t for t in _fails.get(key, []) if t > time.time() - 300]
    _fails[key] = recent
    if len(recent) >= 5:
        raise HTTPException(429, "Слишком много попыток. Подождите 5 минут.")


def login_failed(key: str):
    _fails.setdefault(key, []).append(time.time())


# ---------- сессии ----------
def new_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=SESSION_DAYS)).isoformat(sep=" ", timespec="seconds")
    with session() as c:
        c.execute("INSERT INTO auth_session (token, user_id, expires_at) VALUES (?, ?, ?)", (token, user_id, expires))
    return token


def set_cookie(response, request: Request, token: str):
    # За туннелем Cloudflare сайт открыт по https — тогда cookie только для https
    secure = request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https"
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=secure, path="/")


def resolve(token: str | None) -> Me | None:
    if not token:
        return None
    with session() as c:
        row = c.execute(
            "SELECT s.user_id, sh.id AS shop_id FROM auth_session s JOIN shop sh ON sh.user_id = s.user_id "
            "WHERE s.token = ? AND s.expires_at > datetime('now', 'localtime')", (token,)).fetchone()
    return Me(row["user_id"], row["shop_id"]) if row else None


def current(request: Request) -> Me:
    """Зависимость FastAPI: без входа — 401, фронтенд отправит на страницу входа."""
    me = resolve(request.cookies.get(COOKIE))
    if not me:
        raise HTTPException(401, "Нужно войти в аккаунт")
    return me


def ws_user(ws: WebSocket) -> Me | None:
    return resolve(ws.cookies.get(COOKIE))


def drop_session(token: str | None):
    if token:
        with session() as c:
            c.execute("DELETE FROM auth_session WHERE token = ?", (token,))


# ---------- одноразовый вход телефона (QR сканера) ----------
def new_login_token(user_id: int) -> str:
    token = secrets.token_urlsafe(24)
    expires = (datetime.now() + timedelta(minutes=15)).isoformat(sep=" ", timespec="seconds")
    with session() as c:
        c.execute("INSERT INTO login_token (token, user_id, expires_at) VALUES (?, ?, ?)", (token, user_id, expires))
    return token


def use_login_token(token: str) -> int | None:
    # Ключ действует 15 минут и не сгорает при первом открытии: превью ссылки в мессенджере
    # или камера телефона могут открыть её раньше человека
    with session() as c:
        row = c.execute("SELECT user_id FROM login_token WHERE token = ? AND expires_at > datetime('now', 'localtime')",
                        (token,)).fetchone()
    return row["user_id"] if row else None


def client_ip(request: Request) -> str:
    """Настоящий адрес посетителя: за туннелем Cloudflare или прокси Render запросы приходят не напрямую."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return request.headers.get("cf-connecting-ip") or forwarded or (request.client.host if request.client else "")
