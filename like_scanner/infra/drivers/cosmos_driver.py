import json
import logging
import os
import pickle
import time
from typing import List, Dict, Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys

# Import settings values (paths, URLs, user‑agent)
from like_scanner.config import settings

STATE_PATH_COSMOS = settings.STATE_PATH_COSMOS
STATE_PATH_COSMOS_URL = settings.STATE_PATH_COSMOS_URL
USER_AGENT = settings.USER_AGENT

# --------------------------------------------------------------------------- #
# Logging setup
# --------------------------------------------------------------------------- #
logger = logging.getLogger("cosmos")
logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Helper: classic username/password login
# --------------------------------------------------------------------------- #
def perform_cosmos_login(
    driver: webdriver.Chrome,
    login_url: str,
    username: str,
    password: str,
) -> Dict[str, Any]:
    """
    Classic form login for Cosmos.

    1. Opens `login_url`.
    2. Fills the fields id="username" and id="password".
    3. Clicks the button   [data-testid="Login_SignInBtn"].
    4. Waits until the URL no longer contains "login".
    5. On success – saves cookies and returns them.

    Returns
    -------
    {"cookies": list[dict]} on success  |  {"error": str} on failure.
    """
    logger.debug("Opening Cosmos login page: %s", login_url)
    driver.get(login_url)

    # Give potential bot‑protection scripts a moment to render
    time.sleep(2)

    # Wait for the username field to appear
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "username"))
        )
    except TimeoutException:
        return {"error": "Login page did not load in time"}

    try:
        # --- Locate credential inputs robustly --------------------------------
        possible_email_selectors = [
            (By.ID, "username"),
            (By.NAME, "identifier"),
            (By.NAME, "email"),
            (By.CSS_SELECTOR, "input[type='email']"),
            (By.CSS_SELECTOR, "input[placeholder*='Email']"),
            (By.CSS_SELECTOR, "input[autocomplete='username']"),
        ]

        possible_pwd_selectors = [
            (By.ID, "password"),
            (By.NAME, "password"),
            (By.CSS_SELECTOR, "input[type='password']"),
            (By.CSS_SELECTOR, "input[autocomplete='current-password']"),
        ]

        email_input = None
        for by, sel in possible_email_selectors:
            try:
                email_input = driver.find_element(by, sel)
                break
            except NoSuchElementException:
                continue

        pwd_input = None
        for by, sel in possible_pwd_selectors:
            try:
                pwd_input = driver.find_element(by, sel)
                break
            except NoSuchElementException:
                continue

        if not email_input or not pwd_input:
            return {"error": "Login form inputs not found – selectors outdated."}

        # Inputs may be covered by an overlay or marked readonly until focus.
        for field, value in ((email_input, username), (pwd_input, password)):
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable(field)
            )
            field.click()
            field.clear()
            try:
                field.send_keys(value)
            except Exception:
                # Fallback: inject value via JS if element is temporarily read‑only
                driver.execute_script(
                    "arguments[0].removeAttribute('readonly');"
                    "arguments[0].value = arguments[1];"
                    "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
                    field, value,
                )
        logger.debug("Credentials filled for '%s'.", username)

        # First, try submitting with ENTER key (more reliable on Cosmos)
        from selenium.webdriver.common.keys import Keys
        time.sleep(0.3)
        pwd_input.send_keys(Keys.RETURN)
        time.sleep(1)

        # If still on /login, fallback to clicking the button (if visible)
        if "login" in driver.current_url.lower():
            possible_login_btn_selectors = [
                (By.CSS_SELECTOR, "[data-testid='Login_SignInBtn']"),
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH,
                 "//button[contains(translate(., 'ENTER', 'enter'), 'enter')]"),
            ]
            for by, sel in possible_login_btn_selectors:
                try:
                    login_btn = driver.find_element(by, sel)
                    login_btn.click()
                    break
                except NoSuchElementException:
                    continue

        logger.debug("Login form submitted, waiting for redirect…")

        # Successful login ⇒ URL no longer contains /login
        WebDriverWait(driver, 20).until(
            lambda d: "login" not in d.current_url.lower()
        )
    except Exception as exc:
        return {"error": f"Failed to submit login form: {exc}"}

    cookies = driver.get_cookies()
    logger.info("Login successful. %d cookies retrieved.", len(cookies))
    return {"cookies": cookies}


# --------------------------------------------------------------------------- #
# Main driver class for Cosmos
# --------------------------------------------------------------------------- #
class CosmosDriver:
    """
    Selenium WebDriver helper for Cosmos.
    • Manages session cookies persistence.
    • Handles classic username/password login.
    • Provides utility to parse image URLs.
    """

    def __init__(
        self,
        username: str,
        password: str,
        *,
        login_url: str = f"{STATE_PATH_COSMOS_URL}/login",
        headless: bool = True,
    ):
        # --- Selenium options ------------------------------------------------
        chrome_opts = Options()
        chrome_opts.add_argument(
            "--disable-blink-features=AutomationControlled")
        if headless:
            chrome_opts.add_argument("--headless")
            chrome_opts.add_argument("--window-size=1280,900")
        chrome_opts.add_argument(
            "--disable-features=BlockInsecurePrivateNetworkRequests")
        chrome_opts.add_argument("--remote-allow-origins=*")
        chrome_opts.add_argument("--no-sandbox")
        chrome_opts.add_argument("--disable-dev-shm-usage")
        chrome_opts.add_argument("--disable-notifications")
        chrome_opts.add_argument(f"--user-agent={USER_AGENT}")

        self.browser: webdriver.Chrome = webdriver.Chrome(options=chrome_opts)
        self.browser.set_page_load_timeout(30)
        self.browser.implicitly_wait(5)

        logger.info("Chrome WebDriver started (headless=%s).", headless)

        # Try restoring previous session first
        if self._load_cookies():
            logger.info("Existing Cosmos session restored from cookies.")
        else:
            logger.info("No valid session cookies – performing fresh login…")
            result = perform_cosmos_login(
                self.browser, login_url, username, password)
            if "error" in result:
                self.browser.quit()
                raise RuntimeError(f"Cosmos login failed: {result['error']}")

            # Persist cookies for future runs
            self._save_cookies()

    # --------------------------------------------------------------------- #
    # Cookie management helpers
    # --------------------------------------------------------------------- #
    def _load_cookies(self) -> bool:
        """Return True if cookies were loaded and session is valid."""
        try:
            if not os.path.exists(STATE_PATH_COSMOS):
                logger.debug("Cookie file not found: %s", STATE_PATH_COSMOS)
                return False

            self.browser.get(STATE_PATH_COSMOS_URL)
            with open(STATE_PATH_COSMOS, "rb") as fh:
                cookies = pickle.load(fh)

            for ck in cookies:
                ck.pop("sameSite", None)
                ck.pop("priority", None)
                try:
                    self.browser.add_cookie(ck)
                except Exception:
                    continue

            self.browser.refresh()
            return self._is_logged_in()

        except Exception as exc:
            logger.warning("Error while loading cookies: %s", exc)
            return False

    def _save_cookies(self) -> None:
        """Persist current session cookies to disk."""
        try:
            os.makedirs(os.path.dirname(STATE_PATH_COSMOS), exist_ok=True)
            with open(STATE_PATH_COSMOS, "wb") as fh:
                pickle.dump(self.browser.get_cookies(), fh)
            logger.debug("Cookies saved to %s", STATE_PATH_COSMOS)
        except Exception as exc:
            logger.error("Failed to save cookies: %s", exc)

    def _is_logged_in(self) -> bool:
        """Detects authenticated state by absence of '/login' in URL."""
        return "login" not in self.browser.current_url.lower()

    # --------------------------------------------------------------------- #
    # Business helpers
    # --------------------------------------------------------------------- #
    def parse_media(self) -> List[str]:
        """Collect image URLs from the Cosmos discover feed."""
        self.browser.get(f"{STATE_PATH_COSMOS_URL}/discover")
        time.sleep(3)

        urls: List[str] = []
        for img in self.browser.find_elements(By.TAG_NAME, "img"):
            src = img.get_attribute("src")
            if src:
                urls.append(src)
        logger.info("Collected %d media items from discover.", len(urls))
        return urls

    # --------------------------------------------------------------------- #
    # Cleanup
    # --------------------------------------------------------------------- #
    def close(self) -> None:
        """Terminate the WebDriver."""
        try:
            self.browser.quit()
        except Exception:
            pass

        logger.info("Chrome WebDriver closed.")


# --------------------------------------------------------------------------- #
# Public helper — mirrors `init_savee_driver` pattern                         #
# --------------------------------------------------------------------------- #
def init_cosmos_driver(*, headless: bool = True) -> CosmosDriver:
    """
    Convenience wrapper used by FastAPI startup code.

    Reads credentials from `like_scanner.config.settings` and returns an
    initialized `CosmosDriver` instance (with cookies restored or with a fresh
    login if necessary).
    """
    return CosmosDriver(
        username=settings.COSMOS_EMAIL,
        password=settings.COSMOS_PASSWORD,
        headless=headless,
    )


# --------------------------------------------------------------------------- #
# Parser function for Cosmos images                                           #
# --------------------------------------------------------------------------- #
def parse_cosmos_profile(driver, profile_url, start_index) -> dict:
    """
    Парсит страницу профиля Cosmos и возвращает информацию о новом элементе.

    Args:
        driver: Selenium webdriver instance
        profile_url: URL профиля для парсинга
        start_index: С какого индекса элемента начинать парсинг

    Returns:
        dict с результатом парсинга: {
            "hit": bool,
            "image_url": str,
            "saves": int,
            "next_index": int,
            "error": str или None
        }
    """
    # Индекс не может быть отрицательным
    start_index = max(0, start_index)

    logger.info(
        f"Запуск парсинга профиля Cosmos: {profile_url}, start_index={start_index}")

    # Добавляем диагностическую информацию
    logger.info("ДИАГНОСТИКА: Начало парсинга Cosmos с индекса %s", start_index)

    # Единый словарь результата (аналогично savee_driver)
    result = {
        "hit": False,
        "image_url": None,
        "saves": 0,
        "next_index": start_index,
        "error": None
    }

    # Проверка авторизации
    if "login" in driver.current_url.lower():
        logger.warning(
            "Не авторизовано на Cosmos. Требуется повторная авторизация.")
        result["error"] = "Требуется авторизация для просмотра профиля"
        return result

    # Переход на профиль, если он ещё не загружен или изменился
    current_url = driver.current_url
    if not current_url.startswith(profile_url):
        try:
            driver.get(profile_url)
            logger.info(f"Открыта страница профиля: {profile_url}")
            # Даем время на загрузку страницы
            time.sleep(3)
        except Exception as e:
            logger.error(f"Ошибка при открытии профиля {profile_url}: {e}")
            result["error"] = f"Не удалось открыть профиль: {e}"
            return result
    else:
        logger.info(
            "Профиль уже загружен в браузере, повторный переход не требуется.")

    # Скроллинг для загрузки контента, если нужно
    max_scrolls = 5
    scrolls_done = 0

    # Собираем все изображения на странице
    image_elements = driver.find_elements(By.TAG_NAME, "img")
    image_count = len(image_elements)

    # Если изображений меньше, чем start_index, нужно скроллить
    while image_count <= start_index and scrolls_done < max_scrolls:
        try:
            driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);")
            logger.info(f"Выполнена прокрутка #{scrolls_done + 1}")
            time.sleep(settings.SCROLL_DELAY_SEC or 2)

            # Обновляем список изображений
            image_elements = driver.find_elements(By.TAG_NAME, "img")
            new_count = len(image_elements)

            if new_count > image_count:
                image_count = new_count
            else:
                # Если количество изображений не увеличилось, возможно, мы достигли конца страницы
                logger.info(
                    "Количество изображений не увеличилось после прокрутки")
                break

            scrolls_done += 1
        except Exception as e:
            logger.warning(f"Ошибка при скроллинге: {e}")
            break

    # Получаем список всех валидных изображений
    image_urls = []
    for img in image_elements:
        src = img.get_attribute("src")
        if src and src.lower().endswith((".webp", ".jpg", ".jpeg", ".png", ".gif")):
            image_urls.append(src)

    logger.info(f"Найдено {len(image_urls)} изображений с валидными URL")

    # Обработка изображений начиная с start_index
    processed = 0
    for idx, url in enumerate(image_urls):
        if idx < start_index:
            processed += 1
            continue  # пропускаем до нужного индекса

        image_url = url
        logger.info(
            f"Обрабатываем изображение по индексу {idx}: URL={image_url}")

        # Попытка найти количество "Connections" для текущего изображения
        connections_count = 0
        try:
            # Делаем скриншот страницы для отладки (временно)
            try:
                screenshot_path = "/tmp/cosmos_debug.png"
                driver.save_screenshot(screenshot_path)
                logger.info(
                    f"ДИАГНОСТИКА: Сохранен скриншот страницы в {screenshot_path}")
            except Exception as e:
                logger.warning(f"Не удалось сделать скриншот: {e}")

            # Находим элемент с изображением
            matching_img = None
            for img in image_elements:
                if img.get_attribute("src") == image_url:
                    matching_img = img
                    logger.info(
                        "ДИАГНОСТИКА: Найдено совпадающее изображение в DOM")
                    break

            if matching_img:
                try:
                    # Получаем позицию изображения
                    img_rect = driver.execute_script(
                        "return arguments[0].getBoundingClientRect();", matching_img)
                    img_x = img_rect['x']
                    img_y = img_rect['y']

                    logger.info(
                        f"ДИАГНОСТИКА: Позиция изображения: x={img_x}, y={img_y}")

                    # Сначала проверяем атрибуты изображения для чисел
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
                    """, matching_img)

                    for attr_name, attr_value in data_attrs.items():
                        if 'connection' in attr_name.lower() or 'count' in attr_name.lower():
                            try:
                                connections_count = int(attr_value)
                                logger.info(
                                    f"ДИАГНОСТИКА: Найдено число connections в атрибуте {attr_name}: {connections_count}")
                                break
                            except:
                                pass

                    # Если не нашли в атрибутах, ищем в соседних элементах
                    if connections_count == 0:
                        # Ищем текст, содержащий "connection" или числа рядом с изображением
                        page_text = driver.execute_script("""
                        function getAllVisibleText() {
                            const walker = document.createTreeWalker(
                                document.body, 
                                NodeFilter.SHOW_TEXT,
                                null, 
                                false
                            );
                            
                            let textNodes = [];
                            let node;
                            while(node = walker.nextNode()) {
                                const text = node.textContent.trim();
                                if (text && node.parentElement.offsetParent !== null) {
                                    const rect = node.parentElement.getBoundingClientRect();
                                    if (rect.width > 0 && rect.height > 0) {
                                        textNodes.push({
                                            text: text,
                                            x: rect.x,
                                            y: rect.y,
                                            width: rect.width,
                                            height: rect.height
                                        });
                                    }
                                }
                            }
                            return textNodes;
                        }
                        return getAllVisibleText();
                        """)

                        # Ищем текст, содержащий "connection" или числа рядом с изображением
                        closest_number = None
                        min_distance = float('inf')

                        for text_obj in page_text:
                            text = text_obj.get('text', '')

                            # Логируем все тексты для анализа
                            logger.info(
                                f"ДИАГНОСТИКА: Найден текст на странице: '{text}'")

                            # Проверяем содержит ли текст слово "connection" и цифры
                            if "connection" in text.lower():
                                logger.info(
                                    f"ДИАГНОСТИКА: Найден текст содержащий 'connection': '{text}'")
                                # Извлекаем числа из текста
                                import re
                                numbers = re.findall(r'\d+', text)
                                if numbers:
                                    connections_count = int(numbers[0])
                                    logger.info(
                                        f"ДИАГНОСТИКА: Извлечено число из текста с connections: {connections_count}")
                                    break

                            # Если текст просто число, проверяем расстояние до изображения
                            elif text.isdigit():
                                # Вычисляем расстояние до изображения
                                text_x = text_obj.get('x', 0)
                                text_y = text_obj.get('y', 0)
                                distance = ((img_x - text_x)**2 +
                                            (img_y - text_y)**2)**0.5

                                logger.info(
                                    f"ДИАГНОСТИКА: Найдено число {text} на расстоянии {distance} пикселей от изображения")

                                # Если это ближайшее к изображению число, запоминаем его
                                if distance < min_distance and distance < 300:  # Максимальное расстояние 300px
                                    closest_number = int(text)
                                    min_distance = distance

                        # Если нашли ближайшее число, используем его
                        if closest_number is not None and connections_count == 0:
                            connections_count = closest_number
                            logger.info(
                                f"ДИАГНОСТИКА: Используем ближайшее число как connections: {connections_count}")

                except Exception as e:
                    logger.warning(
                        f"Ошибка при выполнении JavaScript для поиска текста: {e}")

                # Поиск connections через DOM
                if connections_count == 0:
                    current_elem = matching_img
                    parent_levels = [current_elem]

                    # Проверяем родительские элементы до 8 уровней вверх
                    for level in range(8):
                        if not current_elem:
                            break

                        # Ищем элементы с текстом "connection" или просто числа
                        for selector in [
                            ".//span[contains(text(), 'connection')]",
                            ".//div[contains(text(), 'connection')]",
                            ".//span[text()[not(contains(., ' '))]][string-length(normalize-space()) <= 5]",
                            ".//div[text()[not(contains(., ' '))]][string-length(normalize-space()) <= 5]",
                            ".//span[contains(@class, 'connection')]",
                            ".//div[contains(@class, 'connection')]",
                            ".//span[contains(@class, 'count')]",
                            ".//div[contains(@class, 'count')]"
                        ]:
                            elements = current_elem.find_elements(
                                By.XPATH, selector)
                            for elem in elements:
                                text = elem.text.strip()
                                logger.info(
                                    f"ДИАГНОСТИКА: Найден элемент с селектором {selector}, текст: '{text}'")

                                if text:
                                    # Извлекаем числа из текста
                                    import re
                                    numbers = re.findall(r'\d+', text)
                                    if numbers:
                                        connections_count = int(numbers[0])
                                        logger.info(
                                            f"ДИАГНОСТИКА: Найдено {connections_count} connections через DOM")
                                        break

                            if connections_count > 0:
                                break

                            # Переходим на уровень выше
                            try:
                                current_elem = current_elem.find_element(
                                    By.XPATH, "./..")
                            except:
                                break

            # Если все методы не сработали, попробуем найти число на всей странице
            if connections_count == 0:
                try:
                    # Получаем весь текст страницы и ищем в нем шаблоны connections
                    page_source = driver.page_source.lower()
                    import re

                    # Ищем шаблоны вида "X connections", "X saves", "connection(X)"
                    patterns = [
                        r'(\d+)\s*connections',
                        r'(\d+)\s*saves',
                        r'connection\D*(\d+)',
                        r'connections\D*(\d+)'
                    ]

                    for pattern in patterns:
                        matches = re.findall(pattern, page_source)
                        if matches:
                            connections_count = int(matches[0])
                            logger.info(
                                f"ДИАГНОСТИКА: Найдено {connections_count} через regex в HTML: {pattern}")
                            break
                except Exception as e:
                    logger.warning(f"Ошибка при поиске через regex: {e}")

        except Exception as e:
            logger.warning(
                f"Ошибка при извлечении количества connections: {e}")

        # Удаляем тестовые значения для чистоты тестирования
        # # Для отладки - имитация находок для тестирования
        # # Если не нашли connections обычным способом
        # if connections_count == 0:
        #     # Тестовые значения для проверки логики
        #     test_saves = [18, 21, 15, 22, 30, 10, 35, 5, 25, 19]
        #     if idx < len(test_saves):
        #         connections_count = test_saves[idx]
        #         logger.info(
        #             f"ДИАГНОСТИКА: Использую тестовое значение connections: {connections_count}")

        # Устанавливаем результат для возврата
        result["image_url"] = image_url
        result["saves"] = connections_count
        logger.info(
            f"ДИАГНОСТИКА: Итоговое количество connections: {connections_count}")
        processed += 1
        # Четко указываем, что следующий индекс должен быть увеличен
        result["next_index"] = start_index + processed
        logger.info(
            f"Обработано изображение, новый индекс: {result['next_index']}")
        return result

    # Если дошли до конца списка без обработки изображений
    if processed == 0:
        processed = 1  # хотя бы одну карточку «просмотрели»
    result["next_index"] = start_index + processed
    logger.info(
        f"Новых элементов для указанного индекса не найдено. Просмотрено {processed} карточек. Новый индекс: {result['next_index']}")
    result["error"] = "Новые изображения отсутствуют"
    return result


# --------------------------------------------------------------------------- #
# Stand‑alone helper: interactive cookie bootstrap                            #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    """
    Utility to **manually** bootstrap valid Cosmos cookies.

    Usage:
        python -m like_scanner.infra.drivers.cosmos_driver

    Steps:
        1. A non‑headless Chrome window opens on https://www.cosmos.so/login.
        2. Log in **manually** (handle CAPTCHA / 2FA if prompted).
        3. Return to this terminal and press ENTER.
        4. The script dumps current cookies to `STATE_PATH_COSMOS`.
           Subsequent runs of Like‑Scanner will restore the session without
           interacting with the login form.
    """
    from pathlib import Path

    chrome_opts = Options()
    chrome_opts.add_argument("--disable-blink-features=AutomationControlled")
    chrome_opts.add_argument("--remote-allow-origins=*")
    chrome_opts.add_argument("--disable-notifications")
    chrome_opts.add_argument(f"--user-agent={USER_AGENT}")

    browser = webdriver.Chrome(options=chrome_opts)
    browser.set_page_load_timeout(30)
    browser.get(f"{STATE_PATH_COSMOS_URL}/login")

    input("\n>>> Завершите вход в браузере, затем нажмите ENTER, чтобы сохранить cookies… ")

    # Persist cookies
    Path(os.path.dirname(STATE_PATH_COSMOS)).mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH_COSMOS, "wb") as fh:
        pickle.dump(browser.get_cookies(), fh)
    print(f"✅ Cookies сохранены в {STATE_PATH_COSMOS}")

    browser.quit()
