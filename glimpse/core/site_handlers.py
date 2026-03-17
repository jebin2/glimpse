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

def _ndtv_force_unhide(page: Page):
    """
    Aggressively remove all height/overflow constraints on NDTV article containers.
    Targets both known class names and a broad sweep of any element whose inline
    max-height or overflow:hidden is capping the article.
    """
    page.evaluate("""
        // Known NDTV article container selectors
        const selectors = [
            '.Art-dtl', '.sp-cn', '.Art-exp_bt-wr', '.js-ad-section',
            '.ins_storybody', '.sp-cn-lst', '.story__content',
            '.article__body', '.article-body', '.content-area',
            '[class^="Art-"]', '[class*=" Art-"]'
        ];
        selectors.forEach(sel => {
            try {
                document.querySelectorAll(sel).forEach(node => {
                    node.style.setProperty('max-height', 'none', 'important');
                    node.style.setProperty('height', 'auto', 'important');
                    node.style.setProperty('overflow', 'visible', 'important');
                    node.style.setProperty('opacity', '1', 'important');
                    node.style.setProperty('visibility', 'visible', 'important');
                    node.hidden = false;
                });
            } catch(e) {}
        });
        // Hide the expand-button wrapper so it doesn't obscure content
        document.querySelectorAll('.Art-exp_bt-wr').forEach(el => {
            el.style.setProperty('display', 'none', 'important');
        });
    """)

def handle_ndtv(page: Page):
    try:
        logger_config.info("Handling NDTV: expanding full article content...")

        # Step 1: Try to click the expand button via its known CSS selector.
        # Use Playwright's native .click() (not a JS click) so NDTV's mouse-event
        # listeners actually fire and their JS unhides the content properly.
        clicked = False
        try:
            btn = page.wait_for_selector('.Art-exp_bt-lk', state='visible', timeout=5000)
            if btn:
                btn.scroll_into_view_if_needed()
                time.sleep(0.3)
                btn.click()
                logger_config.info("Clicked NDTV expand button (.Art-exp_bt-lk)")
                clicked = True
                time.sleep(1)
        except Exception as e:
            logger_config.debug(f"NDTV expand button not found via selector: {e}")

        # Step 2: CSS force-unhide always runs — covers both the case where the
        # button click succeeded (belt-and-suspenders) and where no button exists.
        _ndtv_force_unhide(page)

        if not clicked:
            logger_config.debug("No NDTV expand button found; CSS force applied as sole method.")

        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)

    except Exception as e:
        logger_config.error(f"Error handling NDTV full article: {e}")

# Registry of domain to handler functions
SITE_HANDLERS = {
    "nytimes.com": handle_nytimes,
    "www.nytimes.com": handle_nytimes,
    "ndtv.com": handle_ndtv,
    "www.ndtv.com": handle_ndtv
}

# Selectors applied to every site regardless of domain.
GLOBAL_ADS_SELECTORS = [
    '[data-google-query-id]',
]

# Per-site selectors to force-hide after render (persistent MutationObserver).
# Add a domain key and a list of CSS selectors to hide for that site.
ADS_RM_SELECTORS = {
    "bbc.com": [
        '[data-component="advertisement-block"]',
        '[class="dotcom-slot"]',
        '[data-component="ad-slot"]'
    ],
}

def apply_ads_rm_handlers(page: Page, url: str):
    """
    Injects a persistent MutationObserver that force-hides ad elements.
    Always applies GLOBAL_ADS_SELECTORS; additionally applies any per-domain
    selectors defined in ADS_RM_SELECTORS.
    """
    domain = urlparse(url).netloc
    selectors = list(GLOBAL_ADS_SELECTORS)
    for key, sel_list in ADS_RM_SELECTORS.items():
        if key in domain:
            selectors += sel_list
            break

    logger_config.info(f"Injecting ads_rm_handler for {domain}: {selectors}")
    page.evaluate("""(selectors) => {
        function hideAll() {
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    el.style.setProperty('display', 'none', 'important');
                    el.style.setProperty('visibility', 'hidden', 'important');
                    el.style.setProperty('height', '0', 'important');
                    el.style.setProperty('overflow', 'hidden', 'important');
                });
            });
        }
        hideAll();
        const observer = new MutationObserver(hideAll);
        observer.observe(document.body, { childList: true, subtree: true });
    }""", selectors)

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
