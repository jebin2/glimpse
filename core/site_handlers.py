from urllib.parse import urlparse
from playwright.sync_api import Page
import time
from custom_logger import logger_config

def handle_nytimes(page: Page):
    try:
        logger_config.info("Looking for NYTimes cookie warning...")

        # target the specific button ID, but filter for the one that is actually visible on screen
        accept_btn = page.locator("#fides-accept-all-button >> visible=true").first

        # WAIT for it to appear (this is the important part)
        accept_btn.wait_for(state="visible", timeout=15000)

        # click safely (handles overlay/animation)
        accept_btn.click()

        # wait until the overlay disappears so scrolling works
        accept_btn.wait_for(state="hidden", timeout=10000)

        logger_config.info("Dismissed NYTimes cookie warning.")

    except Exception as e:
        logger_config.error(f"Error handling NYTimes cookie popup: {e}")

# Registry of domain to handler functions
SITE_HANDLERS = {
    "nytimes.com": handle_nytimes,
    "www.nytimes.com": handle_nytimes
}

def apply_site_handlers(page: Page, url: str):
    domain = urlparse(url).netloc
    
    for key, handler in SITE_HANDLERS.items():
        if domain == key or domain.endswith("." + key):
            logger_config.info(f"Applying custom site handler for {key}...")
            handler(page)
            # Wait for network idle after handling popup if it triggered requests
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except:
                pass
            break
