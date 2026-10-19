"""Настройки из файла .env (токен бота и т. п.). Сам .env в репозиторий не попадает."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "daptar_ai_bot").strip().lstrip("@")

# МРП на 2026 год и лимит упрощёнки 600 000 МРП (Налоговый кодекс 2026)
MRP_2026 = 4325
SIMPLIFIED_LIMIT = 600_000 * MRP_2026

# Оплата сервиса Дәптер: процент с реально полученных денег (оплаченные продажи + возвращённые долги).
# По интервью с магазином: от 0,5% до 2%. Реквизиты для оплаты вписываются в .env.
SERVICE_RATE = min(max(float(os.getenv("SERVICE_RATE", "0.01") or 0.01), 0.005), 0.02)
SERVICE_KASPI = os.getenv("SERVICE_KASPI", "").strip()
SERVICE_KASPI_NAME = os.getenv("SERVICE_KASPI_NAME", "").strip()

# Адрес сайта на сервере (Render задаёт RENDER_EXTERNAL_URL сам). Пусто — сайт запущен на ноутбуке.
PUBLIC_URL = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
# Секрет, по которому сервер узнаёт, что запрос на /tg/webhook пришёл именно от Telegram
import hashlib as _hashlib
WEBHOOK_SECRET = _hashlib.sha256(("daptar-webhook:" + BOT_TOKEN).encode()).hexdigest()[:48] if BOT_TOKEN else ""

# Единственный администратор. Логин и пароль — только в .env / настройках сервера, в коде их нет.
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
