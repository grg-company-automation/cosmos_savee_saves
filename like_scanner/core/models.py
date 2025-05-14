# like_scanner/core/models.py
"""
Domain-модели Like-Scanner’а.

* **MediaItem**  – одна карточка (картинка/видео).
* **ScanResult** – результат обработки одной карточки.
* **ConfigRow**  – строка из листа `config` (Google Sheets).

Все конструкторы логируют своё создание, чтобы в терминале
был чёткий «трейл» действий пайплайна.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from pydantic import BaseModel, Field, validator

from .constants import LIKES_THRESHOLD

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .models import ScanResult  # for type hints inside continue_parse

# ──────────────────────────────
# Глобальный логгер для моделей
# ──────────────────────────────
logger = logging.getLogger("like_scanner.models")
if not logger.handlers:                       # не плодим дубликаты при повторном импорте
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)-7s %(name)s ▶ %(message)s")
    )
    logger.addHandler(_h)
logger.setLevel(logging.DEBUG)


# ══════════════════════════════
#            MODELS
# ══════════════════════════════
class MediaItem(BaseModel):
    """
    Представление одной медиа-карточки в профиле.

    * `index`      – порядковый номер (0-based) в ленте профиля  
    * `url`        – прямой *.webp* / *.mp4* CDN-URL  
    * `saves`      – число лайков/сохранений на платформе  
    * `scraped_at` – UTC-время, когда бот увидел карточку
    """

    index: int = Field(..., ge=0)
    url: str = Field(..., description="Absolute http(s) media URL")
    saves: int = Field(..., ge=0)
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    # ——— валидаторы ———
    @validator("url")
    def _url_must_be_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v

    # ——— Хук: логируем создание модели ———
    def __init__(self, **data):
        super().__init__(**data)
        logger.debug(
            "MediaItem  idx=%-4s saves=%-3s url=%s",
            self.index,
            self.saves,
            self.url[:80] + ("…" if len(self.url) > 80 else ""),
        )


class ScanResult(BaseModel):
    """
    Результат однократного вызова парсера (`process_one`).

    * `hit`         – True, если карточка >= LIKES_THRESHOLD  
    * `next_index`  – какой индекс запрашивать при следующем цикле  
    * `item`        – MediaItem (только когда hit=True)  
    * `error`       – строка ошибки (`end_of_profile`, `no_hits` …)
    """

    hit: bool
    next_index: int = Field(..., ge=0)
    item: Optional[MediaItem] = None
    error: Optional[str] = None

    # ——— гарантируем консистентность ———
    @validator("item", always=True)
    def _item_required_on_hit(cls, v, values):
        if values.get("hit") and v is None and not values.get("error"):
            raise ValueError("item must be provided when hit is True")
        return v

    def __init__(self, **data):
        super().__init__(**data)
        # ——— Логируем результат ———
        if self.error:
            logger.warning(
                "ScanResult ERROR='%s' next_index=%s", self.error, self.next_index
            )
        else:
            logger.info(
                "ScanResult hit=%s  saves=%s  next_index=%s",
                self.hit,
                self.item.saves if self.item else "—",
                self.next_index,
            )


class ConfigRow(BaseModel):
    """
    Строка конфигурации из листа **config** Google Sheets.
    """

    index: int = Field(..., ge=0)
    profile_url: str
    platform: str = Field(pattern=r"^(savee|cosmos)$")

    def __init__(self, **data):
        super().__init__(**data)
        logger.debug("ConfigRow  idx=%s  platform=%s  url=%s",
                     self.index, self.platform, self.profile_url)


# ══════════════════════════════
#        SESSION TRACKER
# ══════════════════════════════
@dataclass
class SessionTracker:
    """
    Отслеживает прогресс сканирования одного профиля.

    * `driver`      – Selenium‑драйвер (опц.)
    * `settings`    – объект настроек (config.Settings), опц.
    * `next_index`  – индекс, который нужно обработать при следующем вызове
    * `fails`       – сколько подряд miss’ов было
    """
    driver: object | None = None
    settings: object | None = None
    next_index: int = 0
    fails: int = 0

    def hit(self, step: int = 1) -> None:
        """Картинка подошла под порог – сбрасываем fails и двигаем индекс."""
        self.next_index += step
        self.fails = 0
        logger.debug("SessionTracker.hit() → next_index=%s fails=%s",
                     self.next_index, self.fails)

    def miss(self, step: int = 1) -> None:
        """Картинка НЕ подошла – увеличиваем fails и индекс."""
        self.next_index += step
        self.fails += 1
        logger.debug("SessionTracker.miss() → next_index=%s fails=%s",
                     self.next_index, self.fails)

    def to_dict(self) -> dict:
        """Удобно логировать или записывать в Sheets."""
        return {"next_index": self.next_index, "fails": self.fails}

    def continue_parse(self) -> "ScanResult":
        """
        Заглушка: вызывает простой пропуск одного индекса без хита.

        В дальнейшем сюда можно вставить реальный вызов парсера
        (savee_parser.process_one / cosmos_parser.process_one) и логику
        обновления fails / next_index на основании результата.

        Сейчас возвращает ScanResult(hit=False, next_index+1).
        """
        self.miss(step=1)  # считаем, что текущая карта «мимо»
        return ScanResult(
            hit=False,
            next_index=self.next_index,
            item=None,
            error=None,
        )

    # ────────────────────────────
    #   continue_parse (stub)
    # ────────────────────────────
    def continue_parse(self) -> "ScanResult":
        """
        Заглушка, чтобы роуты не падали.

        Логика:
        • если драйвер и settings переданы, здесь могли бы вызываться
          реальные парсеры (savee_process / cosmos_process);
        • сейчас просто возвращаем ScanResult(hit=False) и
          двигаем индекс на +1, чтобы сохранить совместимость с роутами.
        """
        # для совместимости импортируем здесь, чтобы избежать кругового импорта
        from like_scanner.core.models import ScanResult

        self.miss(step=1)  # увеличиваем fails и next_index
        return ScanResult(
            hit=False,
            next_index=self.next_index,
            item=None,
            error=None,
        )


# ──────────────────────────────
# Модуль загружен
# ──────────────────────────────
logger.debug("models.py loaded — LIKES_THRESHOLD=%s", LIKES_THRESHOLD)
