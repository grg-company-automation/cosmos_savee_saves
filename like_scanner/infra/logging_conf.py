import logging
import os
from logging.handlers import TimedRotatingFileHandler
try:
    # Получаем уровень логирования из настроек (если определено)
    from settings import LOG_LEVEL as LOG_LEVEL_SETTING
except ImportError:
    LOG_LEVEL_SETTING = None

# Определяем уровень логирования (INFO по умолчанию, либо DEBUG)
level_str = (LOG_LEVEL_SETTING or os.getenv("LOG_LEVEL", "INFO")).upper()
level = logging.DEBUG if level_str == "DEBUG" else logging.INFO

# Убедимся, что директория для логов существует
os.makedirs("logs", exist_ok=True)

# Создаём обработчик для вывода в файл с ежедневной ротацией и 7 бэкапами
file_handler = TimedRotatingFileHandler(
    filename="logs/bot.log", when="midnight", interval=1, backupCount=7, encoding="utf-8"
)
# Создаём обработчик для вывода в консоль
console_handler = logging.StreamHandler()

# Задаём формат для логов
formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Регистрируем глобальный логгер и добавляем ему обработчики
logger = logging.getLogger()  # корневой логгер
logger.setLevel(level)
logger.addHandler(file_handler)
logger.addHandler(console_handler)
