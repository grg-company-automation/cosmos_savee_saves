import logging
from core.models import ScanResult
# Assuming parse_savee_profile and check_uniqueness are provided by the project:
from drivers.savee_driver import parse_savee_profile
import re

logger = logging.getLogger(__name__)


def process_one(driver, profile_url: str, index: int) -> ScanResult:
    """
    Process a single image or video card from a Savee profile by index.
    Returns a ScanResult indicating whether the item meets the criteria (20+ saves) and related data.
    """
    try:
        # Step 1: Navigate to the profile page (if not already there) and scroll to the target card.
        logger.info(f"Navigating to Savee profile: {profile_url}")
        driver.get(profile_url)  # Navigate to the profile page
        logger.info(f"Scrolling to card at index {index}")

        # Step 2: Extract the card data using the Savee profile parser.
        card = parse_savee_profile(driver, profile_url, index)
        logger.debug(f"Extracted card data at index {index}: {card}")

        # If no card is found (e.g., index out of range), handle as a failure.
        if not card:
            error_msg = f"No card found at index {index}"
            logger.error(error_msg)
            return ScanResult(hit=False, error=error_msg)

        # Build card_url for result usage
        card_url = card.get('url') if isinstance(card, dict) else None
        if not card_url:
            # If card is not a dict or has no URL, try to retrieve from element (if card is a WebElement)
            try:
                card_url = card.get_attribute('href')
            except Exception as e:
                card_url = None

        # Step 4: Determine the number of saves (likes) for this card.
        # Parse the saves count from the card data.
        saves_text = None
        saves_count = 0
        if isinstance(card, dict):
            saves_text = card.get('saves')
        else:
            # If card is a WebElement, find the element containing the saves count text
            try:
                saves_element = card.find_element(
                    By.XPATH, ".//*[contains(text(), 'Save')]")
                saves_text = saves_element.text
            except Exception as e:
                saves_text = None
        if saves_text:
            # Extract numeric part and convert to int
            try:
                # Remove any commas and non-digit characters, then convert to int
                match = re.search(r'\d+', saves_text.replace(',', ''))
                if match:
                    saves_count = int(match.group())
            except Exception as e:
                logger.warning(
                    f"Failed to parse saves count from text '{saves_text}': {e}")
                saves_count = 0
        else:
            logger.warning(
                f"No saves count found for card at index {index}, defaulting to 0.")
            saves_count = 0

        logger.info(f"Card at index {index} has {saves_count} saves")

        # Step 5: Check if the saves count meets the threshold (20 or more).
        if saves_count >= 20:
            logger.info(
                f"Card at index {index} meets the threshold (>= 20 saves). Marking as hit.")
            return ScanResult(hit=True, url=card_url, error=None)
        else:
            logger.info(
                f"Card at index {index} does not meet the threshold (< 20 saves).")
            return ScanResult(hit=False, error=None)

    except Exception as e:
        # Log the exception with traceback and return a ScanResult indicating failure.
        logger.error(
            f"Error processing Savee profile {profile_url} at index {index}: {e}", exc_info=True)
        return ScanResult(hit=False, error=str(e))
