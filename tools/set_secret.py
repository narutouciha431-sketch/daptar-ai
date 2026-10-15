"""Записывает секрет (токен бота, ключ Gemini) в .env прямо из буфера обмена.
Секрет не печатается на экран и никуда, кроме .env, не попадает.

Как пользоваться: скопируйте ключ (кнопка «Copy key»), затем запустите
    .venv\\Scripts\\python.exe tools\\set_secret.py GEMINI_API_KEY
"""
import re
import subprocess
import sys
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"
FORMATS = {
    "BOT_TOKEN": (r"\d+:[\w-]{30,}", "токен от @BotFather"),
    "GEMINI_API_KEY": (r"[\w.\-]{30,}", "ключ из Google AI Studio"),
    "GROQ_API_KEY": (r"[\w.\-]{30,}", "ключ из console.groq.com"),
}

name = sys.argv[1] if len(sys.argv) > 1 else "GEMINI_API_KEY"
pattern, hint = FORMATS.get(name, (r".{10,}", "секрет"))

input(f"Скопируйте {hint} (кнопка «Copy key») и нажмите Enter здесь. Вставлять ничего не нужно.")
value = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                       capture_output=True, text=True, encoding="utf-8").stdout.strip()

if not re.fullmatch(pattern, value):
    print(f"В буфере обмена не {hint}. Скопируйте ключ ещё раз и запустите программу снова.")
    raise SystemExit(1)

lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
lines = [l for l in lines if not l.startswith(name + "=")] + [f"{name}={value}"]
ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
# Очищаем буфер обмена, чтобы ключ случайно не вставился куда-нибудь ещё
subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value ' '"], capture_output=True)
print(f"Готово: {name} сохранён в .env (длина {len(value)} символов, на экран не выводился). Напишите в чат «готово».")
