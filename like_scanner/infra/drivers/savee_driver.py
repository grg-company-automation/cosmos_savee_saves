import logging
import pickle
import tempfile
import time

from like_scanner.config import settings

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# Инициализация логгера для текущего модуля
logger = logging.getLogger('like_scanner.infra.drivers.savee_driver')


def init_driver():
    """Инициализация Chrome WebDriver для Savee в headless-режиме с загрузкой cookies."""
    logger.info("Инициализация Selenium-драйвера для Savee в headless-режиме...")
    # Настройка опций Chrome
    options = Options()
    options.headless = True  # запуск без интерфейса
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Создаём временный профиль пользователя
    temp_profile_dir = tempfile.mkdtemp(prefix="savee_profile_")
    options.add_argument(f"--user-data-dir={temp_profile_dir}")
    logger.info(f"Создан временный профиль для Chrome: {temp_profile_dir}")
    # Установка пользовательского агента из настроек
    user_agent = getattr(settings, "USER_AGENT", None)
    if user_agent:
        options.add_argument(f"--user-agent={user_agent}")
        logger.info(f"User-Agent установлен: {user_agent}")
    else:
        logger.warning(
            "USER_AGENT не указан в настройках, используется по умолчанию")
    # Инициализация Chrome WebDriver
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        logger.error(f"Ошибка запуска WebDriver: {e}")
        raise  # пробрасываем исключение, т.к. драйвер критически не запустился
    logger.info("WebDriver успешно запущен.")
    # Загрузка сохранённых cookies из файла
    state_path = getattr(settings, "STATE_PATH_SAVEE", None)
    if state_path:
        try:
            with open(state_path, "rb") as cookie_file:
                cookies = pickle.load(cookie_file)
            logger.info(
                f"Загружено cookies из {state_path}: {len(cookies)} шт.")
            # Переходим на базовый домен, чтобы установить cookies
            driver.get("https://savee.it")
            for cookie in cookies:
                # Убираем атрибуты, которые могут мешать добавлению cookie
                cookie_data = cookie.copy()
                cookie_domain = cookie_data.get("domain")
                if cookie_domain and "savee" not in cookie_domain:
                    # пропускаем cookie не для домена Savee
                    continue
                # удалить sameSite, если есть
                cookie_data.pop("sameSite", None)
                try:
                    driver.add_cookie(cookie_data)
                except Exception as e:
                    logger.warning(
                        f"Не удалось добавить cookie {cookie_data.get('name')}: {e}")
            driver.refresh()  # Обновляем страницу, чтобы cookie вступили в силу
            logger.info("Cookies успешно добавлены в браузер.")
        except FileNotFoundError:
            logger.info(
                f"Файл с cookies не найден по пути {state_path}. Пропускаем загрузку cookies.")
        except Exception as e:
            logger.error(f"Ошибка при загрузке cookies: {e}")
    else:
        logger.warning(
            "STATE_PATH_SAVEE не указан в настройках, загрузка cookies пропущена.")
    # Если cookies не загрузились или драйвер всё ещё на странице логина – пробуем magic‑link
    if ("login" in driver.current_url.lower()) or ("log in" in driver.page_source.lower()):
        logger.info("Попытка авторизации через magic‑link Savee...")
        magic_status = perform_savee_login(driver)
        if magic_status.get("status") == "success":
            logger.info("Magic‑link авторизация успешна.")
        else:
            logger.error("Magic‑link авторизация не удалась: %s",
                         magic_status.get("message"))
    return driver


def perform_savee_login(driver, login_url: str | None = None) -> dict:
    """Выполняет авторизацию на Savee. Возвращает словарь со статусом и сообщением."""
    if login_url is None:
        login_url = getattr(settings, "STATE_PATH_SAVEE_URL", None)
    if not login_url:
        logger.error(
            "STATE_PATH_SAVEE_URL not provided; cannot perform Savee login.")
        return {"status": "error", "message": "Magic‑link not provided"}
    logger.info(f"Переход на страницу авторизации: {login_url}")
    try:
        driver.get(login_url)
    except Exception as e:
        logger.error(f"Не удалось открыть страницу логина: {e}")
        return {"status": "error", "message": f"Ошибка открытия {login_url}: {e}"}
    # Ожидание загрузки страницы и потенциальной авторизации
    # даём время на редирект после входа (если cookie уже были валидны)
    time.sleep(5)
    current_url = driver.current_url
    imgs = driver.find_elements(By.TAG_NAME, "img")
    if "login" not in current_url.lower() and len(imgs) > 0:
        # Успешная авторизация (мы не на странице /login, и на странице есть изображения)
        logger.info(f"Авторизация успешна, текущий URL: {current_url}")
        # Сохранение cookies в файл состояния
        state_path = getattr(settings, "STATE_PATH_SAVEE", None)
        if state_path:
            try:
                with open(state_path, "wb") as cookie_file:
                    pickle.dump(driver.get_cookies(), cookie_file)
                logger.info(f"Cookies сохранены в файл: {state_path}")
            except Exception as e:
                logger.error(
                    f"Ошибка при сохранении cookies в {state_path}: {e}")
        else:
            logger.warning(
                "STATE_PATH_SAVEE не задан, cookies не сохранены на диск.")
        return {"status": "success", "message": "Login successful"}
    else:
        # Не удалось авторизоваться
        logger.error(f"Авторизация не удалась. Текущий URL: {current_url}")
        return {"status": "error", "message": "Login failed or not authenticated"}


def parse_savee_profile(driver, profile_url, start_index) -> dict:
    """Парсит страницу профиля Savee и возвращает информацию о новом элементе (изображении/видео)."""
    # Индекс не может быть отрицательным
    start_index = max(0, start_index)

    logger.info(
        f"Запуск парсинга профиля: {profile_url}, start_index={start_index}")
    # Единый словарь результата (как в cosmos_driver)
    result = {
        "hit": False,
        "image_url": None,
        "saves": 0,
        "next_index": start_index,
        "error": None
    }

    # Добавляем диагностическую информацию
    logger.info("ДИАГНОСТИКА: Начало парсинга Savee с индекса %s", start_index)

    # Проверка авторизации (если на странице присутствует кнопка входа или подобный признак)
    page_source = driver.page_source.lower()
    if "log in" in page_source or "login" in driver.current_url.lower():
        logger.warning(
            "Не авторизовано на Savee. Пытаемся загрузить cookies и обновить сессию...")
        state_path = getattr(settings, "STATE_PATH_SAVEE", None)
        if state_path:
            try:
                with open(state_path, "rb") as cookie_file:
                    cookies = pickle.load(cookie_file)
                # открываем домен перед добавлением cookie
                driver.get("https://savee.it")
                for cookie in cookies:
                    cookie_data = cookie.copy()
                    cookie_data.pop("sameSite", None)
                    try:
                        driver.add_cookie(cookie_data)
                    except Exception as e:
                        logger.warning(
                            f"Не удалось добавить cookie {cookie_data.get('name')}: {e}")
                # пробуем снова открыть профиль после загрузки cookies
                driver.get(profile_url)
                logger.info(
                    "Cookies загружены из файла, повторно открываем профиль.")
            except Exception as e:
                logger.error(
                    f"Не удалось загрузить cookies для авторизации: {e}")
                result["error"] = "Авторизация требуется, но загрузка cookies не удалась"
                return result
        else:
            logger.error("Отсутствует файл с cookies, авторизация невозможна.")
            result["error"] = "Требуется авторизация для просмотра профиля"
            return result
    # Переход на профиль, если он ещё не загружен или изменился
    current_url = driver.current_url
    if not current_url.startswith(profile_url):
        try:
            driver.get(profile_url)
            logger.info(f"Открыта страница профиля: {profile_url}")
        except Exception as e:
            logger.error(f"Ошибка при открытии профиля {profile_url}: {e}")
            result["error"] = f"Не удалось открыть профиль: {e}"
            return result
    else:
        logger.info(
            "Профиль уже загружен в браузере, повторный переход не требуется.")

    # ─── Умный скроллинг ──────────────────────────────────────────────
    # Если уже загруженных карточек достаточно, прокрутка не нужна.
    max_scrolls = 5          # ограничение «защиты от зависания»
    scrolls_done = 0

    while True:
        # Сколько карточек сейчас в DOM?
        current_imgs = driver.find_elements(By.TAG_NAME, "img")
        current_videos = driver.find_elements(By.TAG_NAME, "video")
        current_count = len(current_imgs) + len(current_videos)

        if current_count > start_index:
            logger.debug(
                "В DOM уже %s карточек (> start_index=%s) — скролл не требуется.",
                current_count, start_index)
            break

        if scrolls_done >= max_scrolls:
            logger.warning(
                "Достигнут лимит прокруток (%s), карточек всё ещё %s ≤ start_index=%s",
                max_scrolls, current_count, start_index)
            break

        # Скроллим в самый низ, ждём подгрузку
        scrolls_done += 1
        try:
            driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);")
            logger.info("Прокрутка страницы #%s выполнена", scrolls_done)
        except Exception as e:
            logger.warning("Ошибка при прокрутке: %s", e)
            break

        time.sleep(settings.SCROLL_DELAY_SEC or 2)
    # Сбор всех элементов <img> и <video> на странице
    img_elements = driver.find_elements(By.TAG_NAME, "img")
    video_elements = driver.find_elements(By.TAG_NAME, "video")
    logger.info(
        f"Найдено элементов: изображений - {len(img_elements)}, видео - {len(video_elements)}")
    # Извлекаем URL из элементов и фильтруем по расширению
    media_urls = []
    for img in img_elements:
        src = img.get_attribute("src")
        if src and src.lower().endswith((".webp", ".jpg", ".jpeg", ".png")):
            media_urls.append(src)
    for video in video_elements:
        src = video.get_attribute("src")
        if src and src.endswith(".mp4"):
            media_urls.append(src)
        # Также проверяем вложенные источники <source> внутри видео, если есть
        try:
            source_elems = video.find_elements(By.TAG_NAME, "source")
            for source in source_elems:
                src = source.get_attribute("src")
                if src and src.endswith(".mp4"):
                    media_urls.append(src)
        except Exception:
            pass
    logger.info(
        f"Отфильтровано медиа URL с требуемыми расширениями: {len(media_urls)} шт.")
    # Удаляем дубликаты URL, если появились
    media_urls = list(dict.fromkeys(media_urls))
    logger.info(f"Уникальных URL после удаления дубликатов: {len(media_urls)}")

    processed = 0  # сколько изображений обработано в этом вызове
    for idx, url in enumerate(media_urls):
        # Просто выбираем элемент по порядковому индексу без проверки хэша/уникальности
        if idx < start_index:
            processed += 1
            continue  # пропускаем до нужного индекса

        image_url = url
        logger.info(f"Выбрано изображение по индексу {idx}: URL={image_url}")

        # Получаем количество сохранений для этого изображения
        saves_count = 0
        try:
            # Находим все контейнеры с изображениями
            for img in img_elements:
                current_src = img.get_attribute("src")
                if current_src == image_url:
                    logger.info(
                        "ДИАГНОСТИКА: Найдено совпадающее изображение в DOM")

                    # Сначала ищем числа рядом с изображением в разных направлениях DOM
                    current_elem = img
                    parent_levels = [current_elem]

                    # Сначала проверяем самый простой случай - число внутри атрибутов самого изображения
                    data_attrs = driver.execute_script("""
                        var attrs = {};
                        var elem = arguments[0];
                        for (var i = 0; i < elem.attributes.length; i++) {
                            var attr = elem.attributes[i];
                            if (attr.name.startsWith('data-') && !isNaN(parseInt(attr.value))) {
                                attrs[attr.name] = attr.value;
                            }
                        }
                        return attrs;
                    """, img)

                    for attr_name, attr_value in data_attrs.items():
                        if 'save' in attr_name.lower() or 'like' in attr_name.lower():
                            try:
                                saves_count = int(attr_value)
                                logger.info(
                                    f"ДИАГНОСТИКА: Найдено число сохранений в атрибуте {attr_name}: {saves_count}")
                                break
                            except:
                                pass

                    # Если не нашли, продолжаем искать в соседних и родительских элементах
                    # Проверяем до 8 уровней вверх
                    for level in range(8):
                        try:
                            # 1. Ищем span или div с только числом внутри
                            for selector in [
                                ".//span[text()[not(contains(., ' '))]][string-length(normalize-space()) <= 5]",
                                ".//div[text()[not(contains(., ' '))]][string-length(normalize-space()) <= 5]",
                                ".//span[contains(@class, 'save')]",
                                ".//span[contains(@class, 'like')]",
                                ".//span[contains(@class, 'count')]",
                                ".//div[contains(@class, 'save')]",
                                ".//div[contains(@class, 'like')]",
                                ".//div[contains(@class, 'count')]",
                                ".//span",
                                ".//div"
                            ]:
                                elements = current_elem.find_elements(
                                    By.XPATH, selector)
                                for element in elements:
                                    text = element.text.strip()
                                    logger.info(
                                        f"ДИАГНОСТИКА: Найден элемент с селектором {selector}, текст: '{text}'")
                                    if text and text.isdigit():
                                        saves_count = int(text)
                                        logger.info(
                                            f"ДИАГНОСТИКА: Найдено количество сохранений: {saves_count}")
                                        break
                        except Exception as e:
                            logger.warning(
                                f"Ошибка при поиске по селекторам: {e}")

                        # 2. Ищем span или div с только числом внутри
                        for selector in [
                            ".//span[text()[not(contains(., ' '))]][string-length(normalize-space()) <= 5]",
                            ".//div[text()[not(contains(., ' '))]][string-length(normalize-space()) <= 5]",
                            ".//span[contains(@class, 'save')]",
                            ".//span[contains(@class, 'like')]",
                            ".//span[contains(@class, 'count')]",
                            ".//div[contains(@class, 'save')]",
                            ".//div[contains(@class, 'like')]",
                            ".//div[contains(@class, 'count')]",
                            ".//span",
                            ".//div"
                        ]:
                            elements = current_elem.find_elements(
                                By.XPATH, selector)
                            for element in elements:
                                text = element.text.strip()
                                logger.info(
                                    f"ДИАГНОСТИКА: Найден элемент с селектором {selector}, текст: '{text}'")
                                if text and text.isdigit():
                                    saves_count = int(text)
                                    logger.info(
                                        f"ДИАГНОСТИКА: Найдено количество сохранений: {saves_count}")
                                    break

                        # Если нашли хоть какое-то число, выходим из цикла
                        if saves_count > 0:
                            break

                        # Переходим на следующий уровень
                        if current_elem.parentElement:
                            current_elem = current_elem.parentElement
                        else:
                            break

                    # Если нашли хоть какое-то число, выходим из цикла
                    if saves_count > 0:
                        break
        except Exception as e:
            logger.warning(f"Ошибка при извлечении количества сохранений: {e}")

        # 5. Крайняя мера: проверяем всю страницу на наличие чисел рядом с изображениями
        if saves_count == 0:
            try:
                logger.info("ДИАГНОСТИКА: Поиск чисел на всей странице...")
                # Проверяем весь DOM-дерево, чтобы найти числа
                all_elements = driver.find_elements(By.XPATH, "//*")
                for elem in all_elements:
                    try:
                        text = elem.text.strip()
                        if text and text.isdigit():
                            # Проверяем расстояние до нашего изображения
                            rect1 = img.rect
                            rect2 = elem.rect
                            # Если элемент с числом находится рядом с изображением (например, в пределах 100px)
                            distance = (
                                (rect1['x'] - rect2['x'])**2 + (rect1['y'] - rect2['y'])**2)**0.5
                            if distance < 200:  # примерное расстояние в пикселях
                                saves_count = int(text)
                                logger.info(
                                    f"ДИАГНОСТИКА: Найдено число {saves_count} на расстоянии {distance} пикселей от изображения")
                                break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"Ошибка при поиске чисел на странице: {e}")

        # Устанавливаем результат в зависимости от количества сохранений
        result["image_url"] = image_url
        result["saves"] = saves_count
        logger.info(
            f"ДИАГНОСТИКА: Итоговое количество сохранений: {saves_count}")
        processed += 1  # учитываем текущее изображение
        # Четко указываем, что следующий индекс должен быть увеличен
        result["next_index"] = start_index + processed
        logger.info(
            f"Обработано изображение, новый индекс: {result['next_index']}")
        return result

    # --- Если дошли до конца списка без hit ---
    # Увеличиваем индекс ровно на количество обработанных карточек
    if processed == 0:
        processed = 1  # хотя бы одну карточку «просмотрели»
    result["next_index"] = start_index + processed
    logger.info(
        f"Новых элементов для указанного индекса не найдено. Просмотрено {processed} карточек. Новый индекс: {result['next_index']}")
    result["error"] = "Новые изображения отсутствуют"
    return result
