import logging
from fastapi import Request, HTTPException
from selenium.webdriver.remote.webdriver import WebDriver
from like_scanner.config import settings, Settings

# Logger: initialize logger for this module
logger = logging.getLogger("like_scanner.dependencies")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    # Log format: [YYYY-MM-DD HH:MM:SS] LEVEL    like_scanner.dependencies ▶ message
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-9s%(name)s ▶ %(message)s", "%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Settings


def get_settings() -> Settings:
    """Зависимость FastAPI, возвращающая глобальный объект настроек из config.py.
    Если объект настроек не создан, вызывает HTTP 500 (не ожидается при правильной конфигурации).
    Логирует использование настроек приложения.
    """
    if settings is None:
        logger.error("Settings not initialized in config.py")
        raise HTTPException(
            status_code=500, detail="Application settings are not initialized")
    logger.info("Using Settings from config.py")
    return settings

# Drivers


def get_savee_driver(request: Request) -> WebDriver:
    """Зависимость FastAPI, возвращающая Selenium WebDriver для Savee из app.state.
    Если драйвер недоступен, вызывает HTTP 500.
    Логирует использование драйвера Savee.
    """
    driver = getattr(request.app.state, "driver_savee", None)
    if driver is None:
        logger.error("Savee driver not found in app.state")
        raise HTTPException(
            status_code=500, detail="Savee driver is not initialized")
    logger.info("Using Savee driver from app.state")
    return driver


def get_cosmos_driver(request: Request) -> WebDriver:
    """Зависимость FastAPI, возвращающая Selenium WebDriver для Cosmos из app.state.
    Если драйвер недоступен, вызывает HTTP 500.
    Логирует использование драйвера Cosmos.
    """
    driver = getattr(request.app.state, "driver_cosmos", None)
    if driver is None:
        logger.error("Cosmos driver not found in app.state")
        raise HTTPException(
            status_code=500, detail="Cosmos driver is not initialized")
    logger.info("Using Cosmos driver from app.state")
    return driver
