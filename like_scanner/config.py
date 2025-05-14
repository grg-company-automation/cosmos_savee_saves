"""
like_scanner/config.py
──────────────────────
Единый источник настроек для всего проекта.

• Загружает переменные из .env (если файл найден)
• Наследует pydantic.BaseSettings — значения можно переопределять
  через переменные окружения **или** напрямую из Python
• Экземпляр `settings` создаётся один раз и импортируется в любом модуле:

    from like_scanner.config import settings
    print(settings.COSMOS_EMAIL)

При импорте выводит в лог все считанные параметры.
"""

# NB: Requires `pydantic>=2` and `pydantic-settings` package
# pip install "pydantic[dotenv]" pydantic-settings

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

# ── Загрузить .env (если он присутствует) ───────────────────
env_path = Path(".env")
if env_path.exists():
    load_dotenv(env_path)
else:
    # Пытаемся взять путь из переменной окружения ENV_FILE, если .env в другом месте
    custom_env = os.getenv("ENV_FILE")
    if custom_env and Path(custom_env).exists():
        load_dotenv(custom_env)

# ── Логгер модуля конфигурации ──────────────────────────────
logger = logging.getLogger("like_scanner.config")
if not logger.handlers:
    stream = logging.StreamHandler()
    stream.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s] %(message)s")
    )
    logger.addHandler(stream)
logger.setLevel(logging.INFO)


# ── Pydantic Settings ───────────────────────────────────────
class Settings(BaseSettings):
    # Учётные данные платформ
    COSMOS_EMAIL: str
    COSMOS_PASSWORD: str

    # Magic-link для Savee
    STATE_PATH_SAVEE_URL: str

    # Ссылка для перехода на главную страницу Cosmos
    STATE_PATH_COSMOS_URL: str

    # Пути к JSON/pickle сессиям
    STATE_PATH_SAVEE: str
    STATE_PATH_COSMOS: str

    # Параметры парсинга
    LIKES_THRESHOLD: int = Field(20, description="≥ этого числа → hit")
    MAX_FAILS: int = Field(20, description="подряд miss, после которых стоп")

    # Скроллинг / клики
    CLICK_PAUSE_SEC: float = 1.5
    SCROLL_DELAY_SEC: float = 2.0
    INITIAL_SCROLLS: int = 2

    # Дополнительные лимиты
    DAILY_IMAGE_LIMIT: int = 400
    SCROLL_ITERATIONS: int = 1
    GOOGLE_SEARCH_DELAY_SEC: int = 5

    # User-Agent
    USER_AGENT: str

    # Логи / кэш
    LOG_LEVEL: str = Field(
        "INFO", pattern=r"^(INFO|DEBUG|WARNING|ERROR|CRITICAL)$")
    LOG_PATH: str | None = None
    IMAGE_CACHE_PATH: str | None = None

    # Сервер
    PORT: int = 5000
    UVICORN_WORKERS: int = 1

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

    # ----- валидаторы -----
    @field_validator("LIKES_THRESHOLD", "MAX_FAILS", "PORT", "UVICORN_WORKERS")
    @classmethod
    def _positive_int(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be positive")
        return v

    @field_validator("COSMOS_EMAIL", "COSMOS_PASSWORD", "STATE_PATH_SAVEE_URL")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("cannot be empty")
        return v


# ── Singleton instance ─────────────────────────────────────
settings = Settings()  # type: ignore

# ── Dump to log (masking sensitive) ─────────────────────────


def _mask(val: str) -> str:
    if len(val) <= 4:
        return "***"
    return val[:2] + "***" + val[-2:]


logger.info("📦 Settings loaded:")
for name, value in settings.dict().items():
    if any(k in name.lower() for k in ("password", "email", "token")):
        value = _mask(str(value))
    logger.info("  %-25s = %s", name, value)
