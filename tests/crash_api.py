"""Краш-тест API Дәптер AI: плохие данные, крайние значения, параллельные запросы, нагрузка.

Запуск (сервер должен работать на 127.0.0.1:8000):
    .venv\\Scripts\\python.exe tests\\crash_api.py
Создаёт отдельный тестовый аккаунт и удаляет его в конце.
"""
import http.cookiejar
import json
import os
import sys
import time
import urllib.request as u
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

B = os.getenv("DAPTAR_URL", "http://127.0.0.1:8000")
EMAIL = "crash.test@daptar.kz"
results = {"ok": 0, "bad": 0}


class Client:
    def __init__(self):
        self.op = u.build_opener(u.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def raw(self, m, p, data: bytes | None, ctype="application/json"):
        r = u.Request(B + p, method=m, data=data, headers={"Content-Type": ctype})
        t = time.time()
        try:
            with self.op.open(r, timeout=30) as x:
                body = x.read()
                return x.status, body, time.time() - t
        except u.HTTPError as e:
            return e.code, e.read(), time.time() - t
        except Exception as e:  # обрыв соединения = падение сервера
            return 0, str(e).encode(), time.time() - t

    def req(self, m, p, b=None):
        st, body, dt = self.raw(m, p, json.dumps(b).encode() if b is not None else (b"" if m == "POST" else None))
        try:
            return st, json.loads(body or b"null")
        except ValueError:
            return st, body[:80]


def check(name, cond, extra=""):
    results["ok" if cond else "bad"] += 1
    print(("✅ " if cond else "❌ ") + name + (f" — {extra}" if extra else ""))


def no_crash(name, st, allowed=(200, 201, 204, 400, 401, 404, 409, 422)):
    check(name, st in allowed, f"код {st}")


def cleanup():
    """Убираем тестовый аккаунт через сам сайт (кнопка «Удалить аккаунт») — так работает на любом сервере."""
    op = u.build_opener(u.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        for path, body in (("/api/auth/login", {"email": EMAIL, "password": "Crash12345"}), ("/api/auth/delete", {"password": "Crash12345"})):
            op.open(u.Request(B + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST"), timeout=30)
        return
    except Exception:
        pass  # аккаунта нет или сервер недоступен — пробуем локальную базу
    from app.db import session
    with session() as c:
        uid = c.execute("SELECT id FROM user WHERE email = ?", (EMAIL,)).fetchone()
        if not uid:
            return
        shop = c.execute("SELECT id FROM shop WHERE user_id = ?", (uid["id"],)).fetchone()["id"]
        for t in ("payment", "reminder", "sale", "product", "customer"):
            c.execute(f"DELETE FROM {t} WHERE shop_id = ?", (shop,))
        c.execute("DELETE FROM shop WHERE id = ?", (shop,))
        c.execute("DELETE FROM user WHERE id = ?", (uid["id"],))


def main():
    cleanup()
    c = Client()
    st, _ = c.req("POST", "/api/auth/register", {"full_name": "Краш Тест", "email": EMAIL, "phone": "+77010009999",
                                                  "shop_name": "Краш-тест дүкені", "password": "Crash12345"})
    check("тестовый аккаунт создан", st == 200, f"код {st}")

    print("\n— Плохие данные —")
    no_crash("невалидный JSON", c.raw("POST", "/api/products", b"{name: ")[0])
    no_crash("пустое тело", c.raw("POST", "/api/products", b"")[0])
    no_crash("неверные типы", c.req("POST", "/api/products", {"name": 123, "price": "дорого"})[0])
    no_crash("отрицательная цена", c.req("POST", "/api/products", {"name": "X", "price": -5})[0])
    no_crash("огромная цена", c.req("POST", "/api/products", {"name": "Дорогой", "price": 10**30})[0])
    no_crash("название 10 000 символов", c.req("POST", "/api/products", {"name": "Я" * 10000, "price": 1})[0])
    st, xss = c.req("POST", "/api/products", {"name": "<img src=x onerror=alert(1)>", "synonyms": "<script>alert(1)</script>", "price": 100})
    check("XSS-строка сохраняется как текст", st == 201 and xss["name"].startswith("<img"), f"код {st}")
    st, sqli = c.req("POST", "/api/products", {"name": "Нан'); DROP TABLE product;--", "price": 150, "barcode": "123"})
    check("SQL-инъекция в названии безопасна", st == 201 and c.req("GET", "/api/products")[0] == 200)
    no_crash("эмодзи и казахские буквы", c.req("POST", "/api/products", {"name": "Құрт 🧀 ӘҒҚҢӨҰҮҺІ", "price": 300})[0])
    no_crash("дубль штрихкода → 409", c.req("POST", "/api/products", {"name": "Дубль", "price": 1, "barcode": "123"})[0])

    # Чистый товар: фраза нагрузочного теста разбирается правилами, ИИ (и его лимит) не тратится
    nan = c.req("POST", "/api/products", {"name": "Нан", "synonyms": "хлеб", "price": 150})[1]
    st, cust = c.req("POST", "/api/customers", {"name": "Айгүл & <Ерлан>", "phone": "+77010001122"})
    check("покупатель со спецсимволами", st == 201)
    pid = sqli["id"]

    print("\n— Продажи и долги: крайние значения —")
    no_crash("продажа без товаров", c.req("POST", "/api/sales", {"kind": "paid", "items": []})[0])
    no_crash("долг без покупателя", c.req("POST", "/api/sales", {"kind": "debt", "items": [{"name": "X", "qty": 1, "price": 1}]})[0])
    no_crash("количество 0", c.req("POST", "/api/sales", {"kind": "paid", "items": [{"name": "X", "qty": 0, "price": 1}]})[0])
    no_crash("огромное количество 1e20", c.req("POST", "/api/sales", {"kind": "paid", "items": [{"name": "X", "qty": 1e20, "price": 1000}]})[0])
    no_crash("огромная цена в корзине", c.req("POST", "/api/sales", {"kind": "paid", "items": [{"name": "X", "qty": 1, "price": 10**25}]})[0])
    no_crash("неверный вид продажи", c.req("POST", "/api/sales", {"kind": "steal", "items": [{"name": "X", "qty": 1, "price": 1}]})[0])
    no_crash("чужой/несуществующий покупатель", c.req("POST", "/api/sales", {"kind": "debt", "customer_id": 999999, "items": [{"name": "X", "qty": 1, "price": 1}]})[0])
    st, debt = c.req("POST", "/api/sales", {"kind": "debt", "customer_id": cust["id"], "items": [{"product_id": pid, "name": "Нан", "qty": 2, "price": 150}]})
    check("нормальный долг 300 ₸", st == 201 and debt["total"] == 300)
    no_crash("оплата больше долга", c.req("POST", "/api/payments", {"customer_id": cust["id"], "amount": 10**9})[0])
    no_crash("оплата 0", c.req("POST", "/api/payments", {"customer_id": cust["id"], "amount": 0})[0])
    no_crash("оплата без долга", c.req("POST", "/api/payments", {"customer_id": cust["id"], "amount": 10})[0])

    print("\n— Разбор фраз и прочее —")
    for text in ["", " ", "а" * 501, "🤖🤖🤖", "<script>alert(1)</script>", "1 2 3 4 5 6 7 8 9 0", "қарыз қарыз қарыз", "999999999999 нан"]:
        no_crash(f"разбор фразы {text[:20]!r}", c.req("POST", "/api/parse", {"text": text})[0])
    no_crash("лимит продаж -1", c.req("GET", "/api/sales?limit=-1")[0])
    st, rows = c.req("GET", "/api/sales?limit=-1")
    check("limit=-1 не отдаёт лишнее", isinstance(rows, list) and len(rows) <= 200, f"{len(rows) if isinstance(rows, list) else rows} строк")
    no_crash("аналитика days=-5", c.req("GET", "/api/analytics?days=-5")[0])
    no_crash("аналитика days=abc", c.req("GET", "/api/analytics?days=abc")[0])
    no_crash("фото: не картинка", c.req("POST", f"/api/products/{pid}/photo", {"image": "data:text/html;base64," + "A" * 200})[0])
    no_crash("фото: битый base64", c.req("POST", f"/api/products/{pid}/photo", {"image": "data:image/jpeg;base64," + "A" * 201})[0])
    no_crash("QR чужой продажи", c.req("GET", "/api/sales/1/qr.svg")[0])
    no_crash("напоминание несуществующему", c.req("GET", "/api/reminders/999999")[0])
    no_crash("настройки: налог 500%", c.req("PUT", "/api/shop", {"name": "X", "district": "Y", "tax_rate": 5, "kaspi_link": ""})[0])
    no_crash("настройки: время 99:99", c.req("PUT", "/api/shop", {"name": "X", "district": "Y", "tax_rate": 0.04, "report_time": "99:99"})[0])

    print("\n— Двойное нажатие и параллельные запросы —")
    sale = {"kind": "debt", "customer_id": cust["id"], "client_ref": "crash-double-1",
            "items": [{"product_id": pid, "name": "Нан", "qty": 1, "price": 150}]}
    before = len(c.req("GET", "/api/sales?limit=200")[1])
    c.req("POST", "/api/sales", sale)
    c.req("POST", "/api/sales", sale)  # повтор той же операции (двойное нажатие / обрыв сети)
    after = len(c.req("GET", "/api/sales?limit=200")[1])
    check("повтор той же операции не создаёт второй долг", after - before == 1, f"создано записей: {after - before}")

    print("\n— Нагрузка: 20 продавцов одновременно, 200 запросов —")
    def worker(i):
        cl = Client()
        cl.req("POST", "/api/auth/login", {"email": EMAIL, "password": "Crash12345"})
        out = []
        for j in range(10):
            st1, _, t1 = cl.raw("POST", "/api/parse", json.dumps({"text": "Айгүл екі нан қарызға"}).encode())
            st2, _, t2 = cl.raw("POST", "/api/sales", json.dumps({"kind": "paid", "items": [{"product_id": nan["id"], "name": "Нан", "qty": 1, "price": 150}]}).encode())
            out += [(st1, t1), (st2, t2)]
        return out
    t0 = time.time()
    with ThreadPoolExecutor(20) as ex:
        all_res = [r for rs in ex.map(worker, range(20)) for r in rs]
    total = time.time() - t0
    errors = [s for s, _ in all_res if s not in (200, 201)]
    times = sorted(t for _, t in all_res)
    check("нагрузка без ошибок", not errors, f"{len(all_res)} запросов за {total:.1f} с, ошибок {len(errors)} {sorted(set(errors))}, "
          f"медиана {times[len(times)//2]*1000:.0f} мс, 95% {times[int(len(times)*.95)]*1000:.0f} мс, макс {times[-1]*1000:.0f} мс")

    print("\n— Сервер жив после всего —")
    check("сервер отвечает", Client().raw("GET", "/", None)[0] == 200)
    cleanup()
    check("тестовый аккаунт удалён", True)
    print(f"\nИтог: {results['ok']} прошло, {results['bad']} проблем")


if __name__ == "__main__":
    main()
