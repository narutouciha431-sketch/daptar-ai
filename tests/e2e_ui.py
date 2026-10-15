"""Краш-тест интерфейса в настоящем браузере (Playwright, навык webapp-testing).

Проходит все экраны на ноутбуке и телефоне, ловит ошибки консоли и сервера, горизонтальную прокрутку,
двойное нажатие, XSS. Скриншоты кладёт в tests/screens/ — для проверки внешнего вида.
Запуск (сервер на 127.0.0.1:8000):  .venv\\Scripts\\python.exe tests\\e2e_ui.py
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
from tests.crash_api import cleanup, EMAIL  # noqa: E402

B = "http://127.0.0.1:8000"
SHOTS = Path(__file__).resolve().parent / "screens"
SHOTS.mkdir(exist_ok=True)
report = {"ok": 0, "bad": 0, "notes": []}


def check(name, cond, extra=""):
    report["ok" if cond else "bad"] += 1
    print(("✅ " if cond else "❌ ") + name + (f" — {extra}" if extra else ""))


def watch(page, tag):
    """Собираем ошибки консоли, исключения JS, ответы 5xx и всплывающие alert (признак XSS)."""
    errs = []
    page.on("console", lambda m: errs.append(f"console.{m.type}: {m.text[:160]}") if m.type == "error" and "WebSocket" not in m.text and "401" not in m.text else None)
    page.on("pageerror", lambda e: errs.append(f"JS: {str(e)[:160]}"))
    page.on("response", lambda r: errs.append(f"HTTP {r.status} {r.url[-60:]}") if r.status >= 500 else None)
    page.on("dialog", lambda d: (errs.append(f"DIALOG: {d.message[:80]}"), d.dismiss()))
    return errs


def overflow(page) -> int:
    return page.evaluate("document.documentElement.scrollWidth - window.innerWidth")


def visit_all(page, errs, device):
    for hash_ in ["kassa", "products", "customers", "debts", "cabinet", "settings"]:
        page.goto(f"{B}/app#{hash_}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        page.screenshot(path=str(SHOTS / f"{device}-{hash_}.png"), full_page=True)
        ov = overflow(page)
        check(f"[{device}] {hash_}: нет горизонтальной прокрутки", ov <= 1, f"лишние {ov}px" if ov > 1 else "")
    page.goto(f"{B}/app#cabinet")
    page.wait_for_load_state("networkidle")
    if page.locator("[data-tab=charts]").count():
        page.click("[data-tab=charts]")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(SHOTS / f"{device}-analytics.png"), full_page=True)


def main():
    cleanup()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ---------- ноутбук: регистрация и работа ----------
        ctx = browser.new_context(viewport={"width": 1366, "height": 768}, locale="ru-RU")
        page = ctx.new_page()
        errs = watch(page, "desktop")

        page.goto(B + "/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(SHOTS / "desktop-landing.png"), full_page=True)
        check("главная открылась", page.locator("h1").count() == 1)

        page.goto(B + "/register")
        page.click("#regForm button.main")
        page.wait_for_timeout(300)
        shown = page.locator("#regForm .err:not(:empty)").count()
        check("пустая форма регистрации показывает ошибки", shown >= 5, f"ошибок у полей: {shown}")
        page.screenshot(path=str(SHOTS / "desktop-register-errors.png"), full_page=True)
        page.fill("#rName", "Тестов Тест")
        page.fill("#rEmail", EMAIL)
        page.fill("#rPhone", "8 701 000 99 99")
        page.fill("#rShop", "UI-тест дүкені")
        page.fill("#rPass", "Crash12345")
        page.fill("#rPass2", "Crash12345")
        page.click("#regForm button.main")
        page.wait_for_url("**/app**", timeout=10000)
        check("регистрация через форму → рабочий стол", "/app" in page.url)

        # Прайс: обычный товар и товар с XSS-названием
        page.goto(B + "/app#products")
        page.wait_for_load_state("networkidle")
        for name, syn, price in [("Нан", "хлеб", "200"), ("<img src=x onerror=alert('xss')>", "<b>жирный</b>", "100")]:
            page.fill("#f-name", name); page.fill("#f-syn", syn); page.fill("#f-price", price)
            page.click("#addForm button[type=submit]")
            page.wait_for_timeout(600)
        check("XSS в названии товара не выполнился", not any("DIALOG" in e for e in errs))
        check("товары добавлены через форму", page.locator("#rows tr").count() >= 2)

        # Покупатель
        page.goto(B + "/app#customers")
        page.wait_for_load_state("networkidle")
        page.fill("#custForm input[name=name]", "Айгүл апай")
        page.fill("#custForm input[name=phone]", "+77010001122")
        page.click("#custForm button[type=submit]")
        page.wait_for_timeout(800)

        # Касса: фраза → корзина → двойное нажатие «В долг»
        page.goto(B + "/app#kassa")
        page.wait_for_load_state("networkidle")
        page.fill("#say", "Айгүл апай, екі нан, қарызға")
        page.click("#sayForm button[type=submit]")
        page.wait_for_timeout(1500)
        qty = page.locator("#cart input.qty").first.input_value() if page.locator("#cart input.qty").count() else "нет"
        check("касса разобрала фразу", qty == "2", f"количество хлеба: {qty}")
        before = page.evaluate("fetch('/api/sales?limit=200').then(r => r.json()).then(a => a.length)")
        page.dblclick("#btnDebt")
        page.wait_for_timeout(2000)
        after = page.evaluate("fetch('/api/sales?limit=200').then(r => r.json()).then(a => a.length)")
        check("двойной клик «В долг» создаёт одну запись", after - before == 1, f"создано записей: {after - before}")
        check("после долга показан QR согласия", page.locator("#notice img[alt*=QR]").count() == 1)
        page.screenshot(path=str(SHOTS / "desktop-kassa-consent.png"), full_page=True)

        # Долги: напоминание
        page.goto(B + "/app#debts")
        page.wait_for_load_state("networkidle")
        if page.locator("[data-remind]").count():
            page.click("[data-remind]")
            page.wait_for_timeout(800)
            check("окно напоминания открылось", page.locator("#modal:not([hidden]) textarea").count() == 1)
            page.screenshot(path=str(SHOTS / "desktop-debts-reminder.png"), full_page=True)
            page.click("#mClose")

        # Все экраны на ноутбуке
        visit_all(page, errs, "desktop")

        # Выход
        page.click("#logout")
        page.wait_for_timeout(800)
        page.goto(B + "/app")
        check("после выхода /app ведёт на вход", "/login" in page.url, page.url)
        check("[desktop] ошибок в консоли и сервера нет", not errs, "; ".join(errs[:6]))
        ctx.close()

        # ---------- демо на ноутбуке: аналитика ----------
        ctx = browser.new_context(viewport={"width": 1366, "height": 768}, locale="ru-RU")
        page = ctx.new_page()
        errs = watch(page, "demo")
        page.goto(B + "/login")
        page.click("[data-demo]")
        page.wait_for_url("**/app**")
        page.goto(B + "/app#cabinet")
        page.wait_for_load_state("networkidle")
        page.click("[data-tab=charts]")
        page.wait_for_timeout(2000)
        check("в демо нарисованы 4 графика", page.locator("#cab canvas").count() == 4)
        page.screenshot(path=str(SHOTS / "demo-analytics.png"), full_page=True)
        for h in ["kassa", "debts", "cabinet"]:
            page.goto(f"{B}/app#{h}"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(600)
            page.screenshot(path=str(SHOTS / f"demo-{h}.png"), full_page=True)
        check("[demo] ошибок нет", not errs, "; ".join(errs[:6]))
        ctx.close()

        # ---------- телефон ----------
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="ru-RU")
        page = ctx.new_page()
        errs = watch(page, "mobile")
        page.goto(B + "/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(SHOTS / "mobile-landing.png"), full_page=True)
        check("[mobile] главная без горизонтальной прокрутки", overflow(page) <= 1, f"{overflow(page)}px")
        page.goto(B + "/login")
        page.screenshot(path=str(SHOTS / "mobile-login.png"), full_page=True)
        page.click("[data-demo]")
        page.wait_for_url("**/app**")
        visit_all(page, errs, "mobile")
        page.goto(B + "/scan")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(SHOTS / "mobile-scan.png"), full_page=True)
        check("[mobile] ошибок нет", not errs, "; ".join(errs[:6]))
        ctx.close()
        browser.close()

    cleanup()
    print(f"\nИтог: {report['ok']} прошло, {report['bad']} проблем. Скриншоты: {SHOTS}")


if __name__ == "__main__":
    main()
