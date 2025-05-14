import logging
import re
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from core.models import ScanResult

logger = logging.getLogger(__name__)


def process_one(driver, profile_url: str, index: int) -> ScanResult:
    """
    Navigate to a Cosmos profile (or cluster) page and process one card at the given index.
    - Ensures the profile page is open (navigates if not already on the correct URL).
    - Scrolls the page until at least `index+1` cards are loaded.
    - Clicks the card at the specified index.
    - Waits for the item detail view to open and the saves (connections) count element to appear.
    - Extracts the number of saves (connections) for the item.
    - Determines if the saves count meets the threshold (>= 20).
    - Returns a ScanResult with the outcome and details.
    """
    logger.info(f"Processing profile '{profile_url}' at card index {index}")
    try:
        # Navigate to profile page if not already on it
        if not driver.current_url.startswith(profile_url):
            logger.debug(
                f"Current URL '{driver.current_url}' is not profile URL, navigating to {profile_url}")
            driver.get(profile_url)
            # Optionally wait for page load (e.g., profile name or card container visible)
        else:
            logger.debug(
                f"Already on profile page '{profile_url}', no navigation needed")

        # Scroll until the target card is loaded
        target_count = index + 1
        scroll_attempts = 0
        max_scroll_attempts = 50
        last_count = 0
        # Initial retrieval of cards
        cards = driver.find_elements(By.CSS_SELECTOR, ".css-11m6wtf")
        logger.debug(
            f"Initial cards loaded: {len(cards)} (target {target_count})")
        # Keep scrolling until we have enough cards or reach limits
        while len(cards) < target_count and scroll_attempts < max_scroll_attempts:
            scroll_attempts += 1
            logger.debug(
                f"Scrolling... attempt {scroll_attempts}, currently {len(cards)} cards loaded")
            try:
                driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);")
            except Exception as e:
                logger.warning(
                    f"Exception during scrolling attempt {scroll_attempts}: {e}")
            # Wait a bit for new cards to load
            time.sleep(1)
            cards = driver.find_elements(By.CSS_SELECTOR, ".css-11m6wtf")
            logger.debug(
                f"Cards after scroll attempt {scroll_attempts}: {len(cards)}")
            if len(cards) == last_count:
                # No new cards loaded, break to avoid infinite loop
                logger.debug(
                    "No new cards loaded on last scroll, stopping further scroll attempts")
                break
            last_count = len(cards)
        # After scrolling, check if the desired index is available
        if len(cards) <= index:
            error_msg = f"Card at index {index} not found (only {len(cards)} cards loaded)"
            logger.warning(error_msg)
            return ScanResult(hit=False, url=profile_url, saves=0, next_index=index, error=error_msg)

        # Click the card at the given index
        card = cards[index]
        logger.info(f"Clicking card at index {index}")
        try:
            # Ensure the element is in view before clicking
            driver.execute_script("arguments[0].scrollIntoView(true);", card)
        except Exception as e:
            logger.debug(
                f"Exception scrolling card into view (index {index}): {e}")
        card.click()

        # Wait for the item detail view to open and the saves count element to appear
        logger.debug("Waiting for saves (connections) count element to appear")
        try:
            saves_elem = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, ".css-luxu5na"))
            )
        except TimeoutException:
            error_msg = "Timeout waiting for saves count element"
            logger.warning(error_msg)
            return ScanResult(hit=False, url=profile_url, saves=0, next_index=index, error=error_msg)

        # Extract the number of saves from the element's text
        saves_text = saves_elem.text
        try:
            # Remove any non-digit characters (in case the text includes label) and convert to int
            saves_num = int(''.join(filter(str.isdigit, saves_text)))
        except ValueError:
            error_msg = f"Could not parse saves count from text: '{saves_text}'"
            logger.error(error_msg)
            # Attempt to close the detail overlay before returning
            try:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
            return ScanResult(hit=False, url=profile_url, saves=0, next_index=index, error=error_msg)

        hit = (saves_num >= 20)
        logger.info(
            f"Saves count for card index {index}: {saves_num} (hit={hit})")
        next_index = index + 1

        # Close the item detail view or navigate back to profile page
        if driver.current_url and not driver.current_url.startswith(profile_url):
            # If clicking the card changed the URL (e.g., new route for detail), go back
            logger.debug("Navigating back to profile page from detail view")
            try:
                driver.back()
            except Exception as e:
                logger.error(f"Error navigating back from detail view: {e}")
        else:
            # If URL didn't change (modal overlay), attempt to close the overlay via ESC key
            logger.debug("Closing detail overlay via ESC key")
            try:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception as e:
                logger.error(f"Error sending ESC to close overlay: {e}")
        # Optionally wait for the overlay to close (saves_elem to become stale or card grid visible again)
        try:
            WebDriverWait(driver, 5).until(EC.staleness_of(saves_elem))
        except Exception:
            pass

        # Return the result
        return ScanResult(hit=hit, url=profile_url, saves=saves_num, next_index=next_index, error=None)

    except Exception as e:
        # Catch-all for any unexpected errors
        logger.error(
            f"Error processing profile '{profile_url}' at index {index}: {e}", exc_info=True)
        return ScanResult(hit=False, url=profile_url, saves=0, next_index=index, error=str(e))
