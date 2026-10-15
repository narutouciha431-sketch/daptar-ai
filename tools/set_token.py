"""Записывает токен бота в .env. Токен никуда, кроме .env, не попадает."""
import os
import re
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"

# Обычный ввод: скрытый (getpass) в этом терминале не принимает вставку
token = input("Вставьте токен от @BotFather (правая кнопка мыши или Ctrl+V) и нажмите Enter:\n> ").strip()
if not re.fullmatch(r"\d+:[\w-]{30,}", token):
    print("Это не похоже на токен бота (формат 1234567890:ABC...). Ничего не изменено.")
    raise SystemExit(1)

lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
lines = [l for l in lines if not l.startswith("BOT_TOKEN")]
lines.insert(0, f"BOT_TOKEN={token}")
if not any(l.startswith("BOT_USERNAME") for l in lines):
    lines.append("BOT_USERNAME=daptar_ai_bot")
ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
os.system("cls" if os.name == "nt" else "clear")  # убираем токен с экрана
print("Готово: токен сохранён в .env. Напишите в чат «готово».")
