"""Модуль схем данных (Pydantic-моделей) для FastAPI-приложения Like-Scanner.
Содержит определения входных и выходных схем данных, включая классы:
- ParseContinueRequest
- AuthRequest
- ScanResponse

Каждая модель добавляет запись в лог при создании экземпляра.
Логгер модуля "like_scanner.schemas" настроен с уровнем INFO и форматом '▶'.
"""
import logging
from pydantic import BaseModel, Field
from typing import Optional

# Настройка логгера для текущего модуля
logger = logging.getLogger("like_scanner.schemas")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("▶ %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class ParseContinueRequest(BaseModel):
    """Входная схема для продолжения парсинга (общая для Savee и Cosmos)."""
    next_index: int = Field(...,
                            description="Индекс элемента, с которого продолжить парсинг")

    def __init__(self, **data):
        super().__init__(**data)
        logger.info(
            f"Инициализирован {self.__class__.__name__} с данными: {self.dict()}")


class AuthRequest(BaseModel):
    """Входная схема для авторизации (если требуется URL профиля)."""
    profile_url: str = Field(..., description="URL профиля для авторизации")

    def __init__(self, **data):
        super().__init__(**data)
        logger.info(
            f"Инициализирован {self.__class__.__name__} с данными: {self.dict()}")


# --- Platform‑specific aliases ------------------------------------------
class SaveeAuthRequest(AuthRequest):
    """Авторизация для Savee (пока совпадает со стандартной)."""
    pass


class CosmosAuthRequest(AuthRequest):
    """Авторизация для Cosmos (пока совпадает со стандартной)."""
    pass


class SaveeContinueRequest(ParseContinueRequest):
    """Продолжение парсинга для Savee."""
    pass


class CosmosContinueRequest(ParseContinueRequest):
    """Продолжение парсинга для Cosmos."""
    pass


class ScanResponse(BaseModel):
    """Универсальный ответ сканера."""
    hit: bool = Field(..., description="Признак обнаружения совпадения")
    image_url: Optional[str] = Field(
        None, description="URL изображения (если доступно)")
    saves: Optional[int] = Field(
        None, description="Количество сохранений (если применимо)")
    next_index: int = Field(...,
                            description="Индекс следующего элемента для продолжения парсинга")
    error: Optional[str] = Field(
        None, description="Сообщение об ошибке (если произошла ошибка)")

    def __init__(self, **data):
        super().__init__(**data)
        logger.info(
            f"Инициализирован {self.__class__.__name__} с данными: {self.dict()}")


__all__ = [
    "ParseContinueRequest",
    "AuthRequest",
    "SaveeContinueRequest",
    "CosmosContinueRequest",
    "SaveeAuthRequest",
    "CosmosAuthRequest",
    "ScanResponse",
]
