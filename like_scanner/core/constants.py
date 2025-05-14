# like_scanner/core/constants.py
"""
Like-Scanner: глобальные бизнес-константы.

▪ При старте модуля читаем переменные окружения (если заданы)  
▪ Каждый final-value выводим в терминал, чтобы DevOps видел,
  с чем именно поднялся процесс.  
▪ Никаких внешних зависимостей — «core» остаётся чистым.
"""

from __future__ import annotations

import logging
import os

# ─────────────────────────────────────────────
#  Логгер (один на модуль, предотвращаем дубли)
# ─────────────────────────────────────────────
logger = logging.getLogger("like_scanner.constants")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)-7s %(name)s ▶ %(message)s")
    )
    logger.addHandler(_h)
logger.setLevel(logging.DEBUG)


# ─────────────────────────────────────────────
#  Helper-функции чтения env-переменных
# ─────────────────────────────────────────────
def _int_env(var: str, default: int) -> int:
    val = os.getenv(var)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        logger.warning("ENV %s='%s' не int → fallback=%s", var, val, default)
        return default


def _float_env(var: str, default: float) -> float:
    val = os.getenv(var)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        logger.warning("ENV %s='%s' не float → fallback=%s", var, val, default)
        return default


# ─────────────────────────────────────────────
#  Бизнес-пороговые значения
# ─────────────────────────────────────────────
LIKES_THRESHOLD: int = _int_env("LIKES_THRESHOLD", 20)
MAX_FAILS: int = _int_env("MAX_FAILS", 20)

# ─────────────────────────────────────────────
#  Тайминги Selenium / парсинга
# ─────────────────────────────────────────────
CLICK_PAUSE_SEC: float = _float_env("CLICK_PAUSE_SEC", 1.5)
SCROLL_DELAY_SEC: float = _float_env("SCROLL_DELAY_SEC", 1.0)
INITIAL_SCROLLS: int = _int_env("INITIAL_SCROLLS", 2)

# ─────────────────────────────────────────────
#  User-Agent по умолчанию (можно переопределить)
# ─────────────────────────────────────────────
DEFAULT_USER_AGENT: str = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) LikeScanner/1.0 (+https://gr-group.example)",
)

# ─────────────────────────────────────────────
#  Пути и токены для авторизации / кэша
# ─────────────────────────────────────────────
# Savee: авторизация одной magic-ссылкой, куки храним в JSON
SAVEE_MAGIC_LINK_URL: str | None = os.getenv("STATE_PATH_SAVEE_URL")
STATE_PATH_SAVEE: str | None = os.getenv("STATE_PATH_SAVEE")

# Cosmos: обычный e-mail / пароль, плюс JSON-cookies
STATE_PATH_COSMOS: str | None = os.getenv("STATE_PATH_COSMOS")

# ─────────────────────────────────────────────
#  Дополнительные лимиты и задержки (из старого проекта)
# ─────────────────────────────────────────────
DAILY_IMAGE_LIMIT: int = _int_env("DAILY_IMAGE_LIMIT", 400)
SCROLL_ITERATIONS: int = _int_env("SCROLL_ITERATIONS", 1)
GOOGLE_SEARCH_DELAY_SEC: int = _int_env("GOOGLE_SEARCH_DELAY_SEC", 5)

# Пути для логов и кэша (не критично для core-логики,
# но выводим в _dump() чтобы DevOps видел, что подхватилось)
LOG_PATH: str | None = os.getenv("LOG_PATH")
IMAGE_CACHE_PATH: str | None = os.getenv("IMAGE_CACHE_PATH")

# ─────────────────────────────────────────────
#  Dump всех актуальных значений при импорте
# ─────────────────────────────────────────────


def _dump() -> None:
    logger.info("🚀 Like-Scanner constants загружены:")
    for k, v in sorted(globals().items()):
        if k.isupper():
            logger.info("  %-17s = %s", k, v)

        # Предупреждение, если не передали magic-ссылку Savee
        if not SAVEE_MAGIC_LINK_URL:
            logger.warning(
                "ENV STATE_PATH_SAVEE_URL не задан — драйвер Savee "
                "не сможет авторизоваться через magic-link."
            )


_dump()
