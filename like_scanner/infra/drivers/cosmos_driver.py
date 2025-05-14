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
