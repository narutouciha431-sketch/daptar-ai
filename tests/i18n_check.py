"""Проверка перевода: все страницы в казахском режиме, список текстов, которые остались на русском.

Запуск (сайт должен работать): python tests/i18n_check.py [адрес]
"""
import os
import sys

from playwright.sync_api import sync_playwright

B = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else os.getenv("DAPTAR_URL", "http://127.0.0.1:8000")

# Текст на странице, который не перевёлся: есть кириллица, перевод его не меняет и это не казахский текст из словаря
FIND = """() => {
  const vals = new Set(); const src = document.querySelector('script[src*="i18n"]');
  const out = new Set();
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = w.nextNode());) {
    const t = n.nodeValue.replace(/\\s+/g, ' ').trim();
    if (!/[а-яё]/i.test(t) || n.parentElement.closest('script,style,textarea,[translate=no]')) continue;
    if (/[әғқңөұүһі]/i.test(t) || (window.__kk && window.__kk.has(t.replace(/[\s.?!:…]+$/, '')))) continue;  // уже казахский
    if (window.tr && window.tr(t) === t) out.add(t.slice(0, 90));
  }
  document.querySelectorAll('[placeholder]').forEach(el => { const v = el.placeholder; if (/[а-яё]/i.test(v) && !/[әғқңөұүһі]/i.test(v)) out.add('placeholder: ' + v); });
  return [...out];
}"""

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1366, "height": 900})
    ctx.add_init_script("try { localStorage.setItem('daptar-lang', 'kk') } catch (e) {}")
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    found = {}
    pg.goto(B + "/", wait_until="networkidle"); pg.wait_for_timeout(800); found["главная"] = pg.evaluate(FIND)
    pg.goto(B + "/register", wait_until="networkidle"); pg.click("#regForm button.main"); pg.wait_for_timeout(500); found["регистрация"] = pg.evaluate(FIND)
    pg.goto(B + "/login", wait_until="networkidle"); found["вход"] = pg.evaluate(FIND)
    pg.click("[data-demo]"); pg.wait_for_url("**/app**"); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(1500)
    for tab in ["kassa", "products", "customers", "debts", "cabinet", "cabinet-charts", "settings"]:
        pg.goto(f"{B}/app#{tab}"); pg.reload(); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(2000)
        if tab == "kassa":
            pg.fill("#say", "Айгүл апай екі нан бір сүт қарызға"); pg.click("#sayForm button[type=submit]"); pg.wait_for_timeout(2500)
            pg.click("#scanBtn"); pg.wait_for_timeout(1500)
        if tab == "debts" and pg.locator(".debt-tile").count():
            pg.locator(".debt-tile").first.click(); pg.wait_for_timeout(1500)
        if tab == "customers" and pg.locator("#crows tr[data-id]").count():
            pg.locator("#crows tr[data-id]").first.click(); pg.wait_for_timeout(1500)
        found[tab] = pg.evaluate(FIND)
    pg.goto(B + "/scan", wait_until="networkidle"); pg.wait_for_timeout(1000); found["сканер"] = pg.evaluate(FIND)
    total = 0
    for k, v in found.items():
        total += len(v)
        print(f"\n== {k}: {len(v)}")
        for t in v:
            print("   ", t)
    print(f"\nВсего непереведённых: {total}; ошибок JS: {len(errors)} {errors[:3]}")
    b.close()
