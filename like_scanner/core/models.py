# like_scanner/core/models.py
"""
Domain-модели Like-Scanner'а.

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
#        SESSION TRACKER
# ══════════════════════════════
@dataclass
class SessionTracker:
    """
    Отслеживает прогресс сканирования одного профиля.

    * `driver`      – Selenium‑драйвер (опц.)
    * `settings`    – объект настроек (config.Settings), опц.
    * `next_index`  – индекс, который нужно обработать при следующем вызове
    * `fails`       – сколько подряд miss'ов было
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
        Выполняет парсинг для текущего индекса и определяет "hit" на основе количества сохранений.

        Вызывает соответствующую функцию парсинга в зависимости от типа драйвера (Savee или Cosmos).
        Сравнивает количество сохранений с порогом LIKES_THRESHOLD.

        Returns:
            ScanResult с результатом парсинга и hit=True, если saves >= LIKES_THRESHOLD.
        """
        # Импортируем парсеры здесь, чтобы избежать циклических импортов
        from like_scanner.infra.drivers.savee_driver import parse_savee_profile
        from like_scanner.infra.drivers.cosmos_driver import parse_cosmos_profile
        from .constants import LIKES_THRESHOLD

        # Логируем важную отладочную информацию о пороге
        logger.info(
            f"ДИАГНОСТИКА: Проверка изображений с индекса {self.next_index}, порог LIKES_THRESHOLD={LIKES_THRESHOLD}")

        if not self.driver:
            logger.warning(
                "Драйвер не инициализирован при вызове continue_parse")
            self.miss(step=1)
            return ScanResult(
                hit=False,
                next_index=self.next_index,
                item=None,
                error="Драйвер не инициализирован"
            )

        # Определяем, какой драйвер используется - Savee или Cosmos
        driver_type = str(type(self.driver)).lower()
        logger.info(f"ДИАГНОСТИКА: Тип драйвера: {driver_type}")

        try:
            # Получаем текущий URL или используем дефолтный для платформы
            current_url = self.driver.current_url
            logger.info(f"ДИАГНОСТИКА: Текущий URL: {current_url}")

            # Не уменьшаем индекс на 1, используем точно переданный индекс
            start_idx = self.next_index

            # Определяем, какую функцию парсинга использовать
            logger.info(f"ДИАГНОСТИКА: Начинаем парсинг с индекса {start_idx}")
            if "cosmos" in driver_type:
                logger.info(
                    f"Определен драйвер Cosmos, парсим по индексу {start_idx}")
                # Парсим профиль Cosmos
                result = parse_cosmos_profile(
                    self.driver, current_url, start_idx)
            else:
                logger.info(
                    f"Определен драйвер Savee, парсим по индексу {start_idx}")
                # Парсим профиль Savee
                result = parse_savee_profile(
                    self.driver, current_url, start_idx)

            logger.info(f"ДИАГНОСТИКА: Результат парсинга: {result}")

            # Проверяем результат
            if result.get("error"):
                logger.warning(f"Ошибка при парсинге: {result['error']}")
                self.miss(step=1)
                return ScanResult(
                    hit=False,
                    next_index=self.next_index,  # Используем обновленный индекс после miss()
                    error=result.get("error")
                )

            # Определяем "hit" на основе сравнения с порогом
            image_url = result.get("image_url")
            saves_count = result.get("saves", 0)

            # Если получено достаточное количество сохранений, считаем это hit
            # Принудительно приводим к int для гарантии корректного сравнения
            saves_count = int(saves_count)
            is_hit = saves_count >= LIKES_THRESHOLD

            logger.info(
                f"ДИАГНОСТИКА: Сравниваем {saves_count} >= {LIKES_THRESHOLD} = {is_hit}")

            # Не вызываем hit() и miss() здесь, т.к. они изменяют next_index
            # Логируем только результат сравнения
            if is_hit:
                logger.info(
                    f"HIT! Изображение {image_url} имеет {saves_count} сохранений (>= {LIKES_THRESHOLD})")
            else:
                logger.info(
                    f"MISS. Изображение {image_url} имеет {saves_count} сохранений (< {LIKES_THRESHOLD})")

            # Обновляем счетчик fails непосредственно здесь
            if is_hit:
                self.fails = 0
            else:
                self.fails += 1

            # Создаем MediaItem только если это hit
            item = None
            if is_hit and image_url:
                item = MediaItem(
                    index=start_idx,  # исходный индекс
                    url=image_url,
                    saves=saves_count
                )

            # Сохраняем next_index из результата парсинга, если он есть
            next_idx = result.get("next_index", self.next_index)

            # Возвращаем результат парсинга с обновленным индексом
            scan_result = ScanResult(
                hit=is_hit,
                next_index=next_idx,  # Берем индекс из результата парсера
                item=item,
                error=None
            )

            logger.info(
                f"ДИАГНОСТИКА: Возвращаем результат: hit={is_hit}, next_index={next_idx}, saves={saves_count}")
            return scan_result

        except Exception as e:
            logger.exception(f"Ошибка в процессе парсинга: {e}")
            self.miss(step=1)
            return ScanResult(
                hit=False,
                next_index=self.next_index,
                error=str(e)
            )


# ──────────────────────────────
# Модуль загружен
# ──────────────────────────────
logger.debug("models.py loaded — LIKES_THRESHOLD=%s", LIKES_THRESHOLD)
