"""Снимки слайдов и PDF презентации.

Запуск: .venv\\Scripts\\python.exe pitch\\render.py deck-a   → pitch/out/deck-a/01.png … и pitch/out/deck-a.pdf
Проверяет и вылезание текста за карточки/слайд.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
name = sys.argv[1] if len(sys.argv) > 1 else "deck-a"
out = HERE / "out" / name
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto((HERE / f"{name}.html").as_uri(), wait_until="networkidle")
    pg.evaluate("document.fonts.ready")
    pg.add_style_tag(content=".reveal{opacity:1!important;filter:none!important;transition:none!important} .deck-controls{display:none!important}")
    n = pg.evaluate("document.querySelectorAll('.slide').length")
    for i in range(n):
        pg.evaluate(f"""() => document.querySelectorAll('.slide').forEach((s, k) => {{ s.classList.toggle('active', k === {i}); s.classList.toggle('visible', k === {i}); }})""")
        pg.wait_for_timeout(250)
        over = pg.evaluate(f"""() => {{ const s = document.querySelectorAll('.slide')[{i}], r = s.getBoundingClientRect(), bad = [];
            s.querySelectorAll('h1,h2,h3,p,li,span,b,img,.pasted,.tg').forEach(el => {{ const q = el.getBoundingClientRect();
              if (q.width && (q.right > r.right + 1 || q.bottom > r.bottom + 1 || q.left < r.left - 1)) bad.push((el.textContent || el.alt || el.className).trim().slice(0, 40)); }});
            return bad; }}""")
        if over:
            print(f"слайд {i + 1}: выходит за край → {over[:4]}")
        pg.screenshot(path=str(out / f"{i + 1:02d}.png"))
    pg.emulate_media(media="print")
    pg.pdf(path=str(HERE / "out" / f"{name}.pdf"), width="1920px", height="1080px", print_background=True, margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
    b.close()
pdf = HERE / "out" / f"{name}.pdf"
print(f"{n} слайдов, PDF {pdf.stat().st_size / 1e6:.1f} МБ")
