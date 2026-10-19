"""Проверка администратора: вход, обзор, аккаунты, правка, сброс пароля, блокировка, удаление, права доступа.
Логин и пароль берутся из .env (ADMIN_EMAIL / ADMIN_PASSWORD) и на экран не выводятся.
Запуск: python tests/admin_check.py [адрес]"""
import http.cookiejar, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path
from dotenv import dotenv_values
B = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("DAPTAR_URL", "http://127.0.0.1:8000")).rstrip("/")
env = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
problems = []
def check(name, cond, extra=""):
    print(("✅ " if cond else "❌ ") + name + (f" — {extra}" if extra else ""))
    if not cond: problems.append(name)
def client():
    o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(method, path, body=None):
        req = urllib.request.Request(B + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"}, method=method)
        try:
            r = o.open(req, timeout=60); raw = r.read(); return r.status, (json.loads(raw) if raw[:1] in b"[{" else raw)
        except urllib.error.HTTPError as e:
            return e.code, e.read()[:200]
    return call
adm, user, anon = client(), client(), client()
em = f"adm.test{int(time.time())}@test.kz"
check("пользователь зарегистрирован", user("POST", "/api/auth/register", {"full_name": "Тест Админки", "email": em, "phone": "+77015550044", "shop_name": "Тест", "password": "Parol12345"})[0] == 200)
check("обычный пользователь не видит админку", user("GET", "/api/admin/overview")[0] == 403)
check("без входа админка закрыта", anon("GET", "/api/admin/accounts")[0] == 403)
check("вход администратора", adm("POST", "/api/auth/login", {"email": env["ADMIN_EMAIL"], "password": env["ADMIN_PASSWORD"]})[0] == 200)
check("админ не попадает в кассу", adm("GET", "/api/products")[0] == 401)
st, o = adm("GET", "/api/admin/overview"); check("обзор", st == 200 and o["accounts"] >= 2, f"аккаунтов: {o.get('accounts') if st == 200 else st}")
st, lst = adm("GET", "/api/admin/accounts"); me = next((a for a in lst if a["email"] == em), None) if st == 200 else None
check("аккаунт в списке", bool(me)); uid = me["id"]
check("админа нет в списке", all(a["email"] != env["ADMIN_EMAIL"] for a in lst))
st, a = adm("GET", f"/api/admin/accounts/{uid}"); check("карточка с историей", st == 200 and "sales_list" in a)
check("правка данных", adm("PUT", f"/api/admin/accounts/{uid}", {"full_name": "Новое Имя", "phone": "87015550045", "shop_name": "Новый магазин", "service_rate": 0.015})[0] == 200)
st, a = adm("GET", f"/api/admin/accounts/{uid}"); check("изменения сохранились", a["full_name"] == "Новое Имя" and a["shop_name"] == "Новый магазин" and abs(a["service_rate"] - 0.015) < 1e-9)
st, r = adm("POST", f"/api/admin/accounts/{uid}/password", {}); temp = r.get("password") if st == 200 else None
check("сброс пароля выдал временный", bool(temp))
check("старая сессия пользователя закрыта", user("GET", "/api/auth/me")[0] == 401)
u2 = client(); check("вход с временным паролем", u2("POST", "/api/auth/login", {"email": em, "password": temp})[0] == 200)
check("блокировка", adm("POST", f"/api/admin/accounts/{uid}/block", {"blocked": True})[0] == 200)
check("заблокированный выкинут из сессии", u2("GET", "/api/auth/me")[0] == 401)
check("заблокированный не может войти", client()("POST", "/api/auth/login", {"email": em, "password": temp})[0] == 403)
check("разблокировка", adm("POST", f"/api/admin/accounts/{uid}/block", {"blocked": False})[0] == 200)
check("после разблокировки вход работает", client()("POST", "/api/auth/login", {"email": em, "password": temp})[0] == 200)
demo = next(a for a in lst if a["is_demo"])
check("демо нельзя заблокировать", adm("POST", f"/api/admin/accounts/{demo['id']}/block", {"blocked": True})[0] == 400)
check("демо нельзя удалить", adm("DELETE", f"/api/admin/accounts/{demo['id']}")[0] == 400)
check("удаление аккаунта", adm("DELETE", f"/api/admin/accounts/{uid}")[0] == 200)
check("удалённый не входит", client()("POST", "/api/auth/login", {"email": em, "password": temp})[0] == 401)
check("страница /admin открывается админу", adm("GET", "/admin")[0] == 200)
print(f"\nИтог: {'0 проблем' if not problems else str(len(problems)) + ' проблем'}")
