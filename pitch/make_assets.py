"""Материалы для презентации: свежие скриншоты сайта и сжатые фото интервью.

Сайт поднимается отдельно на порту 8010 на КОПИИ базы со сброшенным демо-магазином —
настоящая база и запущенный сайт не трогаются. Бот выключен (BOT_TOKEN пустой).
Запуск: .venv\\Scripts\\python.exe pitch\\make_assets.py [папка_с_фото]
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
IMG = Path(__file__).resolve().parent / "img"
IMG.mkdir(exist_ok=True)
PORT = 8010
BASE = f"http://127.0.0.1:{PORT}"

SERVER = r"""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from app import db
db.DB_PATH = Path(sys.argv[1])
db.init_db()
from app import analytics
analytics.reset_demo(1)
# для слайдов: у демо-истории обычные имена вместо «Демо: …» (только в этой копии базы)
with db.session() as c:
    for old, new in [("Демо: Айгүл апай", "Гүлнар"), ("Демо: Ерлан", "Бауыржан"), ("Демо: Мадина", "Әсел"), ("Демо: Нұрлан ағай", "Дәурен ағай")]:
        c.execute("UPDATE customer SET name = ? WHERE name = ?", (new, old))
import uvicorn
uvicorn.run("app.main:app", host="127.0.0.1", port=%d, log_level="warning")
""" % PORT


def start_server():
    tmp = Path(tempfile.mkdtemp()) / "pitch.db"
    shutil.copy(ROOT / "data" / "daptar.db", tmp)
    env = {**os.environ, "BOT_TOKEN": "", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([sys.executable, "-c", SERVER, str(tmp), str(ROOT)], cwd=ROOT, env=env)
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/", timeout=2)
            return proc
        except Exception:
            time.sleep(1)
    proc.terminate()
    raise SystemExit("сервер для скриншотов не запустился")


def photos(src: Path, browser):
    """Фото интервью: уменьшаем до 1600 px по длинной стороне через браузер (без лишних библиотек)."""
    page = browser.new_page()
    for i, f in enumerate(sorted(src.glob("*.jpg"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0), 1):
        page.goto(f.resolve().as_uri())
        data = page.evaluate("""() => { const im = document.images[0]; const k = Math.min(1, 1600 / Math.max(im.naturalWidth, im.naturalHeight));
            const c = document.createElement('canvas'); c.width = im.naturalWidth * k; c.height = im.naturalHeight * k;
            c.getContext('2d').drawImage(im, 0, 0, c.width, c.height); return c.toDataURL('image/jpeg', 0.84).split(',')[1]; }""")
        import base64
        (IMG / f"interview1-{i}.jpg").write_bytes(base64.b64decode(data))
    page.close()


def shots(browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5, locale="ru-RU")
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle"); page.wait_for_timeout(800)
    page.screenshot(path=str(IMG / "site-landing.png"))
    page.goto(BASE + "/login", wait_until="networkidle")
    page.click("[data-demo]"); page.wait_for_url("**/app**"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(1200)

    page.fill("#say", "Айгүл апай екі нан бір сүт бір шай қарызға")
    page.click("#sayForm button[type=submit]"); page.wait_for_timeout(2500)
    page.screenshot(path=str(IMG / "site-kassa.png"))
    page.click("#btnDebt"); page.wait_for_timeout(2500)
    page.screenshot(path=str(IMG / "site-consent.png"), full_page=False)

    page.goto(BASE + "/app#kassa"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(1000)
    page.click("#scanBtn"); page.wait_for_timeout(1500)
    page.screenshot(path=str(IMG / "site-scan-choice.png"))

    page.goto(BASE + "/app#debts"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(1500)
    page.screenshot(path=str(IMG / "site-debts.png"))
    page.locator(".debt-tile").first.click(); page.wait_for_timeout(1500)
    page.locator("#modal details.tx").first.click(); page.wait_for_timeout(500)
    page.screenshot(path=str(IMG / "site-debt-panel.png"))
    page.keyboard.press("Escape")

    page.goto(BASE + "/app#cabinet"); page.wait_for_load_state("networkidle"); page.wait_for_timeout(2000)
    page.screenshot(path=str(IMG / "site-cabinet.png"))
    page.goto(BASE + "/app#cabinet-charts"); page.reload(); page.wait_for_load_state("networkidle"); page.wait_for_timeout(2500)
    page.screenshot(path=str(IMG / "site-analytics.png"))
    ctx.close()

    m = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="ru-RU")
    mp = m.new_page()
    mp.goto(BASE + "/login", wait_until="networkidle"); mp.click("[data-demo]"); mp.wait_for_url("**/app**"); mp.wait_for_timeout(1500)
    mp.fill("#say", "Ерлан бір нан екі сүт"); mp.click("#sayForm button[type=submit]"); mp.wait_for_timeout(2500)
    mp.screenshot(path=str(IMG / "phone-kassa.png"))
    mp.goto(BASE + "/app#debts"); mp.wait_for_load_state("networkidle"); mp.wait_for_timeout(1500)
    mp.screenshot(path=str(IMG / "phone-debts.png"))
    m.close()


if __name__ == "__main__":
    server = start_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            if len(sys.argv) > 1:
                photos(Path(sys.argv[1]), browser)
            shots(browser)
            browser.close()
    finally:
        server.terminate()
    for f in sorted(IMG.iterdir()):
        print(f"{f.name}: {f.stat().st_size // 1024} КБ")
