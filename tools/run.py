"""Запуск Дәптер AI одной командой: сайт + туннель Cloudflare + ссылка и QR-код для всех устройств.

Остановка: закрыть окно или нажать Ctrl+C.
"""
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import qrcode

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
CLOUDFLARED = ROOT / "tools" / "cloudflared.exe"
LINK_FILE = ROOT / "data" / "link.txt"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def opens(url: str) -> bool:
    try:
        urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "daptar-run"}), timeout=5)
        return True
    except Exception:
        return False


def wait_until(url: str, seconds: int) -> bool:
    """Ждём, пока адрес начнёт открываться."""
    end = time.time() + seconds
    while time.time() < end:
        if opens(url):
            return True
        time.sleep(2)
    return False


def show_link(url: str, ready: bool):
    """Крупно печатаем ссылку и QR-код для телефона, ставим ссылку в заголовок окна."""
    os.system(f"title Daptar AI - {url}")
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    print("\n" + "=" * 64)
    print("  ССЫЛКА ДЛЯ ВСЕХ УСТРОЙСТВ (телефон, другой компьютер):\n")
    print(f"      {url}\n")
    print("  " + ("ГОТОВО: ссылка открывается." if ready else "Ссылка ещё прогревается, попробуйте через минуту."))
    print("  Уже скопирована (Ctrl+V) и сохранена в data\\link.txt.")
    print("  Или наведите камеру телефона на QR-код:")
    qr.print_ascii(invert=True)
    print("  Выключить сайт: закройте это окно или нажмите Ctrl+C.")
    print("=" * 64 + "\n", flush=True)


def start_tunnel(state: dict):
    """Запускаем туннель и в фоне ждём из его журнала новую ссылку."""
    tunnel = subprocess.Popen([str(CLOUDFLARED), "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8000"],
                              cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")

    def read():
        for line in tunnel.stdout:  # журнал туннеля не печатаем — только ищем в нём ссылку
            m = URL_RE.search(line)
            if m and state.get("url") != m.group(0):
                url = m.group(0)
                LINK_FILE.parent.mkdir(exist_ok=True)
                LINK_FILE.write_text(url, encoding="utf-8")
                subprocess.run("clip", input=url, text=True, shell=True)
                state["url"] = url
                show_link(url, wait_until(url, 60))

    threading.Thread(target=read, daemon=True).start()
    return tunnel


def main():
    print("Запускаю сайт…", flush=True)
    site = subprocess.Popen([str(PY), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log", "--log-level", "warning"], cwd=ROOT)
    if not wait_until("http://127.0.0.1:8000/", 60):
        print("Сайт не запустился. Посмотрите ошибки выше.")
        site.terminate()
        sys.exit(1)
    print("Сайт работает на этом ноутбуке: http://127.0.0.1:8000\nПолучаю ссылку для других устройств (10–40 секунд)…", flush=True)

    state = {}
    tunnel = start_tunnel(state)
    fails, last_check = 0, time.time()
    try:
        while site.poll() is None:
            time.sleep(1)
            if tunnel.poll() is not None:
                print("Туннель остановился — запускаю заново, будет новая ссылка…", flush=True)
                state.pop("url", None); tunnel = start_tunnel(state); fails = 0
                continue
            # Раз в минуту проверяем, что ссылка живая; если 3 раза подряд нет (а интернет есть) — новая ссылка
            if state.get("url") and time.time() - last_check > 60:
                last_check = time.time()
                if opens(state["url"]):
                    fails = 0
                elif opens("https://www.cloudflare.com/"):
                    fails += 1
                    if fails >= 3:
                        print("Ссылка перестала открываться — получаю новую…", flush=True)
                        tunnel.terminate(); tunnel.wait(10)
                        state.pop("url", None); tunnel = start_tunnel(state); fails = 0
        print("Сайт остановился. Запустите файл заново.")
    except KeyboardInterrupt:
        print("\nВыключаю…")
    finally:
        for p in (tunnel, site):
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
