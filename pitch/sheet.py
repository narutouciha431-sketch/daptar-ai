"""Обзорный лист: все слайды одной картинкой (для быстрой проверки). Запуск: python pitch/sheet.py deck-a [колонок]"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
HERE = Path(__file__).resolve().parent
name = sys.argv[1]; cols = int(sys.argv[2]) if len(sys.argv) > 2 else 3
imgs = sorted((HERE / "out" / name).glob("*.png"))
html = f"<body style='margin:0;background:#888;display:grid;grid-template-columns:repeat({cols},640px);gap:6px;padding:6px'>" + "".join(
    f"<div style='position:relative'><img src='{p.as_uri()}' style='width:640px;display:block'><b style='position:absolute;left:6px;top:4px;background:#000;color:#fff;padding:2px 6px'>{i+1}</b></div>" for i, p in enumerate(imgs))
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": cols * 646 + 6, "height": 400})
    f = HERE / "out" / f"{name}-sheet.html"; f.write_text(html, encoding="utf-8"); pg.goto(f.as_uri()); pg.wait_for_timeout(800)
    pg.screenshot(path=str(HERE / "out" / f"{name}-sheet.png"), full_page=True); b.close()
