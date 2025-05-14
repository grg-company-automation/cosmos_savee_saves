# like_scanner/core/services.py
"""
Decision-engine Like-Scanner’а.

Задачи модуля:
1.  Обработать данные по карточке (index, saves, url) и решить: **hit / miss**.
2.  Вести счётчик «неудач» подряд и сигнализировать, когда пора остановиться.
3.  Выдавать готовый `ScanResult`, который поймёт любой верхний слой
    (FastAPI-эндпоинт, CLI-скрипт, unit-test).

▶  Никаких Selenium / Google SDK здесь нет — только «чистая» логика.
▶  Подробное логирование *каждого* шага помогает отлаживать пайплайн
   прямо по выводу в терминале или journald.
"""

from __future__ import annotations

import logging
from typing import Optional

from .constants import LIKES_THRESHOLD, MAX_FAILS
from .models import MediaItem, ScanResult

# ──────────────────────────────
#  Логгер
# ──────────────────────────────
logger = logging.getLogger("like_scanner.services")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)-7s %(name)s ▶ %(message)s")
    )
    logger.addHandler(_h)
logger.setLevel(logging.DEBUG)


# ══════════════════════════════
#  SessionTracker
# ══════════════════════════════
class SessionTracker:
    """
    Держит состояние одного «прогона» парсера.

    ➤ `current_index`        – какой элемент сейчас парсер откроет  
    ➤ `consecutive_fails`    – подряд идущие miss’ы (для cut-off)  
    ➤ `max_fails`            – лимит, после которого останавливаемся
    """

    def __init__(self, start_index: int, max_fails: int = MAX_FAILS):
        self.current_index: int = start_index
        self.consecutive_fails: int = 0
        self.max_fails: int = max_fails
        logger.info(
            "📌 Session started  start_index=%s  max_fails=%s",
            self.current_index,
            self.max_fails,
        )

    # ──────────────────────────
    #  Публичный API
    # ──────────────────────────
    def evaluate(
        self, saves: Optional[int], url: Optional[str] = None
    ) -> ScanResult:
        """
        Получает данные карточки и решает, что делать дальше.

        * `saves=None`  → карточка не была найдена (index вышел за предел)
        * `saves < LIKES_THRESHOLD` → miss
        * `saves >= LIKES_THRESHOLD` → hit
        """
        logger.debug(
            "Eval index=%s saves=%s (threshold=%s)", self.current_index, saves, LIKES_THRESHOLD
        )

        # ░░░ 1. Case: reached end of profile  ░░░
        if saves is None:
            result = ScanResult(
                hit=False,
                next_index=self.current_index,  # не меняем, профиль закончился
                error="end_of_profile",
            )
            logger.info("🔚 Profile ended at index=%s", self.current_index)
            return result

        # ░░░ 2. Case: hit ░░░
        if saves >= LIKES_THRESHOLD:
            item = MediaItem(index=self.current_index,
                             url=url or "", saves=saves)
            result = ScanResult(
                hit=True,
                next_index=self.current_index + 1,
                item=item,
            )
            # сбрасываем счётчик неудач
            self.consecutive_fails = 0
            logger.info(
                "✅ HIT  idx=%s  saves=%s  next=%s",
                item.index,
                item.saves,
                result.next_index,
            )
            self.current_index += 1
            return result

        # ░░░ 3. Case: miss ░░░
        self.consecutive_fails += 1
        logger.debug(
            "❌ MISS idx=%s  fails_in_row=%s/%s",
            self.current_index,
            self.consecutive_fails,
            self.max_fails,
        )

        # достигли лимита «no hits»
        if self.consecutive_fails >= self.max_fails:
            result = ScanResult(
                hit=False,
                next_index=self.current_index + 1,
                error="no_hits",
            )
            logger.warning(
                "🛑 MAX_FAILS reached (%s). Stopping scan.", self.consecutive_fails
            )
        else:
            result = ScanResult(
                hit=False,
                next_index=self.current_index + 1,
            )

        self.current_index += 1
        return result
