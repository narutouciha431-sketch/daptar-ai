"""Проверка сайта через внешнюю ссылку (как с телефона и другого компьютера).

Запуск: python tests/external_check.py https://xxxx.trycloudflare.com
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SHOTS = Path(__file__).parent / "screens" / "external"
SHOTS.mkdir(parents=True, exist_ok=True)
problems, ok = [], []


def has(page, sel, timeout=12000):
    """Ждём элемент, а не фиксированное время: через туннель страницы грузятся медленнее."""
    try:
        page.wait_for_selector(sel, timeout=timeout, state="attached")
        return True
    except Exception:
        return False


def check(cond, text):
    (ok if cond else problems).append(text)
    print(("✅ " if cond else "❌ ") + text)


DEVICES = {
    "phone": dict(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                  user_agent="Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36"),
    "pc": dict(viewport={"width": 1366, "height": 768}),
}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for name, opts in DEVICES.items():
        ctx = browser.new_context(**opts, locale="ru-RU")
        page = ctx.new_page()
        errors, failed = [], []
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append((e.stack or str(e))[:300]))
        page.on("requestfailed", lambda r: failed.append(r.url))
        page.on("response", lambda r: r.status >= 400 and failed.append(f"{r.status} {r.url}"))

        page.goto(BASE + "/", wait_until="networkidle", timeout=60000)
        check(page.title() != "", f"[{name}] главная открывается")
        page.screenshot(path=str(SHOTS / f"{name}-landing.png"), full_page=True)
        no_scroll = page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        check(no_scroll, f"[{name}] главная без горизонтальной прокрутки")

        page.goto(BASE + "/login", wait_until="networkidle")
        page.click("[data-demo]")
        page.wait_for_url("**/app**", timeout=30000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)
        live = page.text_content("#live") or ""
        check("онлайн" in live, f"[{name}] живая синхронизация (WebSocket) через туннель: «{live.strip()}»")

        for tab in ["kassa", "products", "customers", "debts", "cabinet", "settings"]:
            page.goto(f"{BASE}/app#{tab}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(SHOTS / f"{name}-{tab}.png"), full_page=True)
            wide = page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            check(wide, f"[{name}] {tab}: без горизонтальной прокрутки")

        # голосовой ввод через текст: разбор фразы
        page.goto(f"{BASE}/app#kassa"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(800)
        page.fill("#say", "Айгүл апай екі нан бір сүт")
        page.click("#sayForm button[type=submit]")
        page.wait_for_timeout(5000)
        rows = page.locator("#cart tr").count()
        check(rows > 0, f"[{name}] касса: фраза разобрана, строк в заказе: {rows}")
        page.click("#clear") if page.locator("#clear").is_visible() else None

        # сканер: QR должен вести на ту же внешнюю ссылку
        info = page.evaluate("fetch('/api/scanner').then(r => r.json())")
        check(info.get("available"), f"[{name}] сканер считается доступным")
        if BASE.startswith("https://"):
            check(info.get("base") == BASE, f"[{name}] QR сканера ведёт на эту же ссылку: {info.get('base')}")

        # новые экраны: кнопка «Сканер» в кассе, сканер в товарах, папки в долгах, оплата сервиса
        has(page, "#scanBtn"); page.click("#scanBtn")
        check(has(page, "#scanBody img[src*='mode=cart']"), f"[{name}] касса → Сканер → QR в режиме «в заказ»")
        page.click("[data-scan=ai]"); page.wait_for_timeout(300)
        check(page.locator("#aiShot").count() == 1, f"[{name}] касса → Сканер → режим «по фото (ИИ)»")
        page.goto(f"{BASE}/app#products"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(800)
        has(page, "#phoneScanP"); page.click("#phoneScanP")
        check(has(page, "#scannerCardP img[src*='mode=price']"), f"[{name}] товары → Сканер на телефоне (режим «в прайс»)")
        page.goto(f"{BASE}/app#debts"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(1200)
        if page.locator(".debt-tile").count():
            page.locator(".debt-tile").first.click(); page.wait_for_timeout(1500)
            check(page.locator("#modal .folder").count() == 3, f"[{name}] долги: 3 папки в панели человека")
            page.screenshot(path=str(SHOTS / f"{name}-debt-panel.png"), full_page=True)
            page.keyboard.press("Escape")
        page.goto(f"{BASE}/app#cabinet"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(1500)
        check(has(page, ".service-card") and "Налог" not in page.inner_text("#cab"), f"[{name}] кабинет: «Оплата сервиса» вместо налога")
        page.goto(BASE + "/scan?mode=price", wait_until="networkidle"); page.wait_for_timeout(800)
        check("on" in (page.get_attribute("#mPrice", "class") or ""), f"[{name}] сканер открывается сразу в режиме «В прайс»")

        page.goto(BASE + "/scan", wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(SHOTS / f"{name}-scan.png"), full_page=True)
        check("/scan" in page.url, f"[{name}] страница сканера открывается ({page.url})")

        # язык
        page.goto(f"{BASE}/app#debts"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(800)
        if page.locator("#langBtn").count():
            page.click("#langBtn"); page.wait_for_timeout(500)
            check("Қарыздар" in page.content(), f"[{name}] переключатель Қаз работает")
            page.click("#langBtn")

        uniq = sorted(set(errors))
        check(not uniq, f"[{name}] ошибок JS нет" + ("" if not uniq else ": " + " | ".join(uniq)[:400]))
        bad = sorted(set(f for f in failed if "favicon" not in f))
        check(not bad, f"[{name}] неудачных запросов нет" + ("" if not bad else ": " + " | ".join(bad)[:500]))
        ctx.close()
    browser.close()

print(f"\nИтог: {len(ok)} прошло, {len(problems)} проблем.")
