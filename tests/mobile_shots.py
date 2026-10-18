"""Скриншоты всех разделов в размере телефона и проверка горизонтальной прокрутки.
Запуск: python tests/mobile_shots.py [адрес]"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
d = Path(__file__).parent / "screens" / "m"; d.mkdir(parents=True, exist_ok=True)
tabs = ["kassa", "products", "customers", "debts", "cabinet", "settings"]
with sync_playwright() as p:
    b = p.chromium.launch()
    c = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True, has_touch=True)
    pg = c.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(B + "/login"); pg.click("[data-demo]"); pg.wait_for_url("**/app**"); pg.wait_for_timeout(1500)
    for t in tabs:
        pg.goto(B + "/app#" + t); pg.wait_for_timeout(1800)
        wide = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
        print(t, "горизонтальная прокрутка" if wide > 1 else "ок")
        pg.screenshot(path=str(d / f"{t}.png"))
    pg.goto(B + "/app#kassa"); pg.wait_for_timeout(1200); pg.click("#scanBtn"); pg.wait_for_timeout(1500)
    pg.screenshot(path=str(d / "scan-overlay.png"))
    print("окно камеры открыто:", pg.locator(".scan-overlay").count() == 1)
    print("ошибки JS:", errs[:3])
    imgs = [d / f"{t}.png" for t in tabs] + [d / "scan-overlay.png"]
    html = "<body style='margin:0;background:#888;display:flex;gap:6px;padding:6px'>" + "".join(f"<img src='{i.resolve().as_uri()}' style='width:250px'>" for i in imgs)
    f = d / "sheet.html"; f.write_text(html, encoding="utf-8")
    s = b.new_page(viewport={"width": 1800, "height": 560}); s.goto(f.resolve().as_uri()); s.wait_for_timeout(600)
    s.screenshot(path=str(d / "sheet.png"), full_page=True)
    b.close()
