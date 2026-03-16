import json
import time
from typing import Callable, Optional
from custom_logger import logger_config
from playwright.sync_api import Page

def find_and_highlight_element(page: Page, text_excerpt: str, color: str = '#00B4D8') -> bool:
    """
    Finds a DOM element containing the given excerpt and highlights it with a background color.
    Uses accurate JS DOM tree walking to locate the text node.
    """
    # JS function to find text node, wrap matching text in <mark>, and style it.
    # Uses window.find which natively searches across HTML tags (like a user pressing Ctrl+F)
    js_code = f"""
    (function() {{
        const excerpt = {json.dumps(text_excerpt)};
        const fullText = excerpt.trim();
        if (!fullText) return {{ success: false, reason: 'Empty excerpt' }};

        // Clear existing selection
        window.getSelection().removeAllRanges();

        // Save scroll position because window.find will aggressively snap the page
        const initialScrollY = window.scrollY;

        // Natively search page for text. This ignores inline HTML tags (a, span, b, etc).
        const found = window.find(fullText, false, false, true, false, false, false);
        
        // Immedately restore original scroll position to prevent jitter
        window.scrollTo(0, initialScrollY);
        
        if (found) {{
            const selection = window.getSelection();
            if (selection.rangeCount > 0) {{
                const range = selection.getRangeAt(0);
                
                const mark = document.createElement('mark');
                mark.style.backgroundColor = '{color}';
                mark.style.color = '#ffffff';
                mark.style.borderRadius = '4px';
                mark.style.padding = '2px 4px';
                mark.style.boxShadow = '0 2px 4px rgba(0,0,0,0.1)';
                mark.setAttribute('data-atv-highlighted', 'true');
                
                try {{
                    // extractContents removes the nodes from document and puts them in a fragment
                    // This handles tags nicely if they don't break block elements
                    mark.appendChild(range.extractContents());
                    range.insertNode(mark);
                    window.getSelection().removeAllRanges();
                    return {{ success: true, method: 'window.find exact' }};
                }} catch (e) {{
                    window.getSelection().removeAllRanges();
                    return {{ success: false, reason: 'extractContents failed across block boundaries: ' + e.toString() }};
                }}
            }}
        }}

        // Fallback: TreeWalker with a much shorter substring to avoid tag boundaries mostly
        const fallbackText = fullText.substring(0, 20).trim();
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node;
        while (node = walker.nextNode()) {{
            if (node.textContent.includes(fallbackText)) {{
                const index = node.nodeValue.indexOf(fallbackText);
                const before = document.createTextNode(node.nodeValue.substring(0, index));
                const after = document.createTextNode(node.nodeValue.substring(index + fallbackText.length));
                
                const mark = document.createElement('mark');
                mark.textContent = fallbackText;
                mark.style.backgroundColor = '{color}';
                mark.style.color = '#ffffff';
                mark.style.borderRadius = '4px';
                mark.setAttribute('data-atv-highlighted', 'true');
                
                const parentNode = node.parentNode;
                parentNode.insertBefore(before, node);
                parentNode.insertBefore(mark, node);
                parentNode.insertBefore(after, node);
                parentNode.removeChild(node);
                
                return {{ success: true, method: 'TreeWalker 20-char fallback' }};
            }}
        }}
        
        return {{ success: false, reason: 'Text not found in DOM at all' }};
    }})();
    """
    result = page.evaluate(js_code)
    success = result.get('success', False)
    if not success:
        logger_config.warning(f"Highlight Failed: '{text_excerpt[:50]}...' Reason: {result.get('reason')}")
    else:
        logger_config.debug(f"Highlight Success ({result.get('method')}) for: '{text_excerpt[:30]}...'")
    return success

def remove_highlights(page: Page):
    """
    Removes the <mark> tags we inserted by unwrapping the text back into the parent node.
    """
    js_code = """
    (function() {
        document.querySelectorAll('mark[data-atv-highlighted="true"]').forEach(mark => {
            const parent = mark.parentNode;
            if (!parent) return;
            // Unpack everything inside the <mark> back into the parent
            while (mark.firstChild) {
                parent.insertBefore(mark.firstChild, mark);
            }
            parent.removeChild(mark);
            parent.normalize();
        });
    })();
    """
    page.evaluate(js_code)


def scroll_to_element(page: Page, text_excerpt: str, offset_y: int = -100) -> bool:
    """
    Find the element by excerpt and smoothly scroll to it.
    offset_y: Add some padding to the top (negative means scroll higher).
    """
    js_code = f"""
    new Promise((resolve) => {{
        const excerpt = {json.dumps(text_excerpt)};
        const fullText = excerpt.trim();
        
        let targetEl = null;
        let absoluteY = 0;
        
        // Save scroll because window.find auto-jumps the viewport
        const initialScrollY = window.scrollY;
        
        // Use window.find to locate coordinates natively
        window.getSelection().removeAllRanges();
        const found = window.find(fullText, false, false, true, false, false, false);
        
        if (found) {{
            const selection = window.getSelection();
            if (selection.rangeCount > 0) {{
                // Find nearest persistent element parent
                let node = selection.getRangeAt(0).startContainer;
                targetEl = (node.nodeType === 3) ? node.parentNode : node;
                if (targetEl && targetEl.getBoundingClientRect) {{
                    // Calculate absolute Y coordinate while we are snapped to the text
                    absoluteY = window.scrollY + targetEl.getBoundingClientRect().top;
                }}
            }}
            window.getSelection().removeAllRanges();
        }}
        
        // Instantly snap back to where we started before starting the smooth animation
        window.scrollTo(0, initialScrollY);
        
        // Fallback
        if (!targetEl) {{
            const fallback = fullText.substring(0, 20);
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while (node = walker.nextNode()) {{
                if (node.textContent.includes(fallback)) {{
                    targetEl = node.parentElement;
                    if (targetEl && targetEl.getBoundingClientRect) {{
                        absoluteY = initialScrollY + targetEl.getBoundingClientRect().top;
                    }}
                    break;
                }}
            }}
        }}

        if (targetEl && absoluteY > 0) {{
            const startY = initialScrollY;
            const targetY = absoluteY + {offset_y};
            const distance = targetY - startY;
            const durationMs = 400;
            const startTime = performance.now();
            
            function easeInOutQuad(t, b, c, d) {{
                t /= d/2;
                if (t < 1) return c/2*t*t + b;
                t--;
                return -c/2 * (t*(t-2) - 1) + b;
            }}

            function scrollStep(timestamp) {{
                const elapsed = Math.max(0, timestamp - startTime);
                if (elapsed < durationMs) {{
                    const nextY = easeInOutQuad(elapsed, startY, distance, durationMs);
                    window.scrollTo(0, nextY);
                    window.requestAnimationFrame(scrollStep);
                }} else {{
                    window.scrollTo(0, targetY);
                    resolve(true);
                }}
            }}
            window.requestAnimationFrame(scrollStep);
        }} else {{
            resolve(false);
        }}
    }});
    """
    success = page.evaluate(js_code)
    return success

def scroll_continuous(page: Page, pixels_per_second: float, duration_seconds: float):
    """
    Kicks off an async JS continuous scroll interpolation over time.
    """
    js_code = f"""
    (function() {{
        const startY = window.scrollY;
        const totalPixels = {pixels_per_second * duration_seconds};
        const endY = startY + totalPixels;
        const durationMs = {duration_seconds * 1000};
        const startTime = performance.now();

        function scrollStep(timestamp) {{
            const elapsed = timestamp - startTime;
            if (elapsed < durationMs) {{
                const progress = elapsed / durationMs;
                window.scrollTo(0, startY + (totalPixels * progress));
                window.requestAnimationFrame(scrollStep);
            }} else {{
                window.scrollTo(0, endY);
            }}
        }}
        window.requestAnimationFrame(scrollStep);
    }})();
    """
    page.evaluate(js_code)

def inject_lower_third(page: Page, name: str, title: str, accent_color: str = '#E63946'):
    """
    Injects a stylish animated lower-third overlay into the DOM.
    """
    js_code = f"""
    (function() {{
        // Remove existing if any
        const existing = document.getElementById('atv-lower-third');
        if (existing) existing.remove();

        const container = document.createElement('div');
        container.id = 'atv-lower-third';
        container.style.position = 'fixed';
        container.style.bottom = '80px';
        container.style.left = '0';
        container.style.display = 'flex';
        container.style.flexDirection = 'row';
        container.style.alignItems = 'stretch';
        container.style.zIndex = '2147483647';
        container.style.fontFamily = 'Arial, Helvetica, sans-serif';
        container.style.transform = 'translateX(-100%)';
        container.style.transition = 'transform 0.6s cubic-bezier(0.22, 1, 0.36, 1)';
        
        const bar = document.createElement('div');
        bar.style.width = '6px';
        bar.style.backgroundColor = '{accent_color}';
        bar.style.borderRadius = '0 3px 3px 0';
        
        const textContainer = document.createElement('div');
        textContainer.style.display = 'flex';
        textContainer.style.flexDirection = 'column';
        
        const nameBox = document.createElement('div');
        nameBox.style.backgroundColor = 'rgba(0, 0, 0, 0.85)';
        nameBox.style.padding = '8px 24px 6px 16px';
        nameBox.style.color = 'white';
        nameBox.style.fontSize = '20px';
        nameBox.style.fontWeight = '700';
        nameBox.style.letterSpacing = '1.5px';
        nameBox.innerText = {json.dumps(name)};
        
        const titleBox = document.createElement('div');
        titleBox.style.backgroundColor = '{accent_color}';
        titleBox.style.padding = '6px 24px 8px 16px';
        titleBox.style.color = 'white';
        titleBox.style.fontSize = '15px';
        titleBox.style.fontWeight = '500';
        titleBox.style.letterSpacing = '0.5px';
        titleBox.style.marginTop = '2px';
        titleBox.innerText = {json.dumps(title)};
        
        textContainer.appendChild(nameBox);
        textContainer.appendChild(titleBox);
        
        container.appendChild(bar);
        container.appendChild(textContainer);
        
        document.body.appendChild(container);
        
        // Trigger reflow
        container.getBoundingClientRect();
        
        // Slide in
        container.style.transform = 'translateX(0)';
    }})();
    """
    page.evaluate(js_code)

def remove_lower_third(page: Page):
    """
    Animates out the lower third overlay and removes it.
    """
    js_code = """
    (function() {
        const el = document.getElementById('atv-lower-third');
        if (el) {
            el.style.transform = 'translateX(-100%)';
            setTimeout(() => el.remove(), 600);
        }
    })();
    """
    page.evaluate(js_code)


def remove_ads(page: Page):
    """
    Injects a global CSS style to hide generic ad containers and promotional blocks
    commonly found on news sites. This creates a cleaner video recording.
    """
    js_code = """
    (function() {
        // List of common ad-related class/ID substrings and specific selectors
        const selectors = [
            '[data-component="advertisement-block"]',
            '.ad-art_wap'
        ];
        
        const style = document.createElement('style');
        style.type = 'text/css';
        style.innerHTML = selectors.join(', ') + ' { display: none !important; height: 0 !important; visibility: hidden !important; }';
        document.head.appendChild(style);
        
        // As a fallback, also brutally remove the nodes if they exist right now
        try {
            const adNodes = document.querySelectorAll(selectors.join(', '));
            adNodes.forEach(node => {
                if(node && node.parentNode) {
                    node.parentNode.removeChild(node);
                }
            });
        } catch(e) {}
    })();
    """
    page.evaluate(js_code)

def trigger_keypoint_transition(page: Page, excerpt: str, label: str, accent_color: str, color_idx: int):
    """
    Batches ALL UI actions for a keypoint into a single JS execution to minimize latency.
    """
    js_code = f"""
    (async function() {{
        // 1. Remove Previous
        document.querySelectorAll('mark[data-atv-highlighted="true"]').forEach(mark => {{
            const parent = mark.parentNode;
            if (parent) {{
                while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
                parent.removeChild(mark);
                parent.normalize();
            }}
        }});
        const existingLT = document.getElementById('atv-lower-third');
        if (existingLT) existingLT.remove();

        // 2. Scroll and Highlight (Approx 400ms)
        const excerpt = {json.dumps(excerpt)};
        const label = {json.dumps(label)};
        const accentColor = {json.dumps(accent_color)};
        
        let targetEl = null;
        let absoluteY = 0;
        const initialScrollY = window.scrollY;

        // Find and get coordinates
        window.getSelection().removeAllRanges();
        if (window.find(excerpt, false, false, true, false, false, false)) {{
            const selection = window.getSelection();
            if (selection.rangeCount > 0) {{
                const range = selection.getRangeAt(0);
                let node = range.startContainer;
                targetEl = (node.nodeType === 3) ? node.parentNode : node;
                if (targetEl && targetEl.getBoundingClientRect) {{
                    absoluteY = window.scrollY + targetEl.getBoundingClientRect().top;
                }}
                
                // Highlight
                const mark = document.createElement('mark');
                mark.style.backgroundColor = accentColor;
                mark.style.color = '#ffffff';
                mark.style.borderRadius = '4px';
                mark.style.padding = '2px 4px';
                mark.setAttribute('data-atv-highlighted', 'true');
                mark.appendChild(range.extractContents());
                range.insertNode(mark);
            }}
            window.getSelection().removeAllRanges();
        }}
        
        window.scrollTo(0, initialScrollY);

        if (targetEl && absoluteY > 0) {{
            const targetY = absoluteY - 100;
            const distance = targetY - initialScrollY;
            const durationMs = 400;
            const startTime = performance.now();
            
            function easeInOutQuad(t, b, c, d) {{
                t /= d/2;
                if (t < 1) return c/2*t*t + b;
                t--;
                return -c/2 * (t*(t-2) - 1) + b;
            }}

            await new Promise(r => {{
                function scrollStep(timestamp) {{
                    const elapsed = timestamp - startTime;
                    if (elapsed < durationMs) {{
                        window.scrollTo(0, easeInOutQuad(elapsed, initialScrollY, distance, durationMs));
                        requestAnimationFrame(scrollStep);
                    }} else {{
                        window.scrollTo(0, targetY);
                        r();
                    }}
                }}
                requestAnimationFrame(scrollStep);
            }});
        }}

        // 3. Inject Lower Third
        const lt = document.createElement('div');
        lt.id = 'atv-lower-third';
        lt.innerHTML = `
            <div style="width:6px; background-color:${{accentColor}}; border-radius:0 3px 3px 0;"></div>
            <div style="display:flex; flex-direction:column;">
                <div style="background-color:rgba(0,0,0,0.85); padding:8px 24px 6px 16px; color:white; font-size:20px; font-weight:700; letter-spacing:1.5px;">KEY POINT</div>
                <div style="background-color:${{accentColor}}; padding:6px 24px 8px 16px; color:white; font-size:15px; font-weight:500; letter-spacing:0.5px; margin-top:2px;">${{label}}</div>
            </div>
        `;
        Object.assign(lt.style, {{
            position: 'fixed', bottom: '80px', left: '0', display: 'flex', zIndex: '2147483647',
            fontFamily: 'Arial, sans-serif', transform: 'translateX(-100%)', transition: 'transform 0.6s'
        }});
        document.body.appendChild(lt);
        lt.getBoundingClientRect();
        lt.style.transform = 'translateX(0)';
    }})();
    """
    page.evaluate(js_code)
