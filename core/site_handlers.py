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

def handle_ndtv(page: Page):
    try:
        logger_config.info("Looking for NDTV 'Read Full Article' / 'Show Full Article' button...", seconds=5)
        
        # In mobile view, NDTV often has a 'Show full article' button that hides content.
        # We look for nodes containing these texts explicitly.
        # Iterate over potential elements since standard locators are timing out or missing it.
        found = False
        elements = page.query_selector_all("a, span, div.Art-exp_bt-lk")
        for el in elements:
            try:
                text = el.inner_text().strip().lower()
                if "show full article" in text or "read full article" in text or "read full story" in text:
                    el.scroll_into_view_if_needed()
                    time.sleep(1)
                    # 1. Try native JS click on the element
                    page.evaluate("node => { try { node.click(); } catch(e) {} }", el)
                    
                    # 2. Force CSS unhide as a brutal fallback
                    page.evaluate("""
                        document.querySelectorAll('.Art-dtl, .sp-cn, .Art-exp_bt-wr, .js-ad-section').forEach(node => {
                            node.style.maxHeight = 'none';
                            node.style.height = 'auto';
                            node.style.overflow = 'visible';
                            node.style.display = 'block';
                        });
                        const expWrapper = document.querySelector('.Art-exp_bt-wr');
                        if (expWrapper) expWrapper.style.display = 'none';
                    """)
                    
                    logger_config.info(f"Clicked NDTV 'Read Full Article' button via JS & CSS force. (Text: {text})")
                    found = True
                    time.sleep(1)
                    page.evaluate("window.scrollTo(0, 0)")
                    time.sleep(2)
                    break
            except Exception:
                continue
                
        if not found:
            logger_config.debug("No NDTV 'Read Full Article' button found; assuming full text.")
            
    except Exception as e:
        logger_config.error(f"Error handling NDTV full article button: {e}")

# Registry of domain to handler functions
SITE_HANDLERS = {
    "nytimes.com": handle_nytimes,
    "www.nytimes.com": handle_nytimes,
    "ndtv.com": handle_ndtv,
    "www.ndtv.com": handle_ndtv
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
