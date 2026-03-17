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
    js_code = f"""
    (function() {{
        const excerpt = {json.dumps(text_excerpt)};
        const fullText = excerpt.trim();
        if (!fullText) return {{ success: false, reason: 'Empty excerpt' }};

        window.getSelection().removeAllRanges();
        const initialScrollY = window.scrollY;
        const found = window.find(fullText, false, false, true, false, false, false);
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
                    mark.appendChild(range.extractContents());
                    range.insertNode(mark);
                    window.getSelection().removeAllRanges();
                    return {{ success: true, method: 'window.find exact' }};
                }} catch (e) {{
                    window.getSelection().removeAllRanges();
                    return {{ success: false, reason: 'extractContents failed: ' + e.toString() }};
                }}
            }}
        }}

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
    Fades out and removes the <mark> tags we inserted.
    """
    js_code = """
    (function() {
        document.querySelectorAll('mark[data-atv-highlighted="true"]').forEach(mark => {
            mark.style.transition = 'opacity 0.3s ease, background-color 0.3s ease';
            mark.style.opacity = '0';
            setTimeout(() => {
                const parent = mark.parentNode;
                if (!parent) return;
                while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
                parent.removeChild(mark);
                parent.normalize();
            }, 300);
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
        const initialScrollY = window.scrollY;

        window.getSelection().removeAllRanges();
        const found = window.find(fullText, false, false, true, false, false, false);

        if (found) {{
            const selection = window.getSelection();
            if (selection.rangeCount > 0) {{
                let node = selection.getRangeAt(0).startContainer;
                targetEl = (node.nodeType === 3) ? node.parentNode : node;
                if (targetEl && targetEl.getBoundingClientRect) {{
                    absoluteY = window.scrollY + targetEl.getBoundingClientRect().top;
                }}
            }}
            window.getSelection().removeAllRanges();
        }}

        window.scrollTo(0, initialScrollY);

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
        container.getBoundingClientRect();
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

def inject_headline_card(page: Page):
    """
    Injects a full-screen headline card for the first ~1.5s of the recording pass.
    Reads the article h1 directly from the DOM. Acts as the viewer hook.
    """
    js_code = """
    (function() {
        const h1 = document.querySelector('h1');
        const title = h1 ? h1.innerText.trim() : document.title.trim();
        if (!title) return;

        const overlay = document.createElement('div');
        overlay.id = 'atv-headline-card';
        Object.assign(overlay.style, {
            position: 'fixed', top: '0', left: '0', width: '100%', height: '100%',
            background: 'linear-gradient(160deg, rgba(10,10,20,0.95) 0%, rgba(30,30,60,0.97) 100%)',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            zIndex: '2147483646', fontFamily: 'Arial, sans-serif',
            opacity: '0', transition: 'opacity 0.35s ease',
            padding: '40px 32px', boxSizing: 'border-box', textAlign: 'center'
        });

        const alarm = document.createElement('div');
        Object.assign(alarm.style, {
            fontSize: '52px', marginBottom: '14px', lineHeight: '1'
        });
        alarm.innerText = '🚨';

        const eyebrow = document.createElement('div');
        Object.assign(eyebrow.style, {
            color: '#E63946', fontSize: '26px', fontWeight: '900',
            letterSpacing: '6px', textTransform: 'uppercase', marginBottom: '24px'
        });
        eyebrow.innerText = 'BREAKING NEWS';

        const titleEl = document.createElement('div');
        Object.assign(titleEl.style, {
            color: 'white', fontSize: '40px', fontWeight: '800',
            lineHeight: '1.3', letterSpacing: '0.2px'
        });
        titleEl.innerText = title;

        const divider = document.createElement('div');
        Object.assign(divider.style, {
            width: '56px', height: '4px', backgroundColor: '#E63946',
            margin: '28px auto 0', borderRadius: '2px'
        });

        overlay.appendChild(alarm);
        overlay.appendChild(eyebrow);
        overlay.appendChild(titleEl);
        overlay.appendChild(divider);
        document.body.appendChild(overlay);

        // Fade in
        overlay.getBoundingClientRect();
        overlay.style.opacity = '1';

        // Fade out after 1.5s
        setTimeout(() => {
            overlay.style.opacity = '0';
            setTimeout(() => overlay.remove(), 350);
        }, 1500);
    })();
    """
    page.evaluate(js_code)


def inject_progress_bar(page: Page, total_duration_ms: float):
    """
    Injects a thin red progress bar at the top that fills over total_duration_ms.
    Self-animates via requestAnimationFrame — no Python polling needed.
    """
    js_code = f"""
    (function() {{
        const existing = document.getElementById('atv-progress-bar');
        if (existing) existing.remove();

        const track = document.createElement('div');
        track.id = 'atv-progress-bar';
        Object.assign(track.style, {{
            position: 'fixed', top: '0', left: '0', width: '100%', height: '4px',
            backgroundColor: 'rgba(255,255,255,0.15)', zIndex: '2147483647', pointerEvents: 'none'
        }});

        const fill = document.createElement('div');
        Object.assign(fill.style, {{
            height: '100%', width: '0%', backgroundColor: '#E63946',
            boxShadow: '0 0 8px rgba(230,57,70,0.7)', borderRadius: '0 2px 2px 0'
        }});

        track.appendChild(fill);
        document.body.appendChild(track);

        const totalMs = {total_duration_ms};
        const startTime = performance.now();

        function update(now) {{
            const pct = Math.min(100, ((now - startTime) / totalMs) * 100);
            fill.style.width = pct + '%';
            if (pct < 100) requestAnimationFrame(update);
        }}
        requestAnimationFrame(update);
    }})();
    """
    page.evaluate(js_code)


def inject_summary_card(page: Page, key_points):
    """
    Injects a full-screen summary card listing all key point labels.
    Fades in immediately and fades out after 2s.
    """
    labels_json = json.dumps([kp.label for kp in key_points])
    js_code = f"""
    (function() {{
        const labels = {labels_json};

        const overlay = document.createElement('div');
        overlay.id = 'atv-summary-card';
        Object.assign(overlay.style, {{
            position: 'fixed', top: '0', left: '0', width: '100%', height: '100%',
            background: 'linear-gradient(160deg, rgba(10,10,20,0.95) 0%, rgba(30,30,60,0.97) 100%)',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            zIndex: '2147483646', fontFamily: 'Arial, sans-serif',
            opacity: '0', transition: 'opacity 0.35s ease',
            padding: '40px 32px', boxSizing: 'border-box'
        }});

        const heading = document.createElement('div');
        Object.assign(heading.style, {{
            color: '#E63946', fontSize: '18px', fontWeight: '800',
            letterSpacing: '5px', textTransform: 'uppercase',
            marginBottom: '28px', textAlign: 'center'
        }});
        heading.innerText = 'KEY POINTS';
        overlay.appendChild(heading);

        labels.forEach((label, i) => {{
            const row = document.createElement('div');
            Object.assign(row.style, {{
                display: 'flex', alignItems: 'center', gap: '14px',
                marginBottom: '16px', width: '100%'
            }});

            const num = document.createElement('div');
            Object.assign(num.style, {{
                width: '30px', height: '30px', borderRadius: '50%',
                backgroundColor: '#E63946', color: 'white',
                fontSize: '14px', fontWeight: '800',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                flexShrink: '0'
            }});
            num.innerText = i + 1;

            const text = document.createElement('div');
            Object.assign(text.style, {{
                color: 'white', fontSize: '20px', fontWeight: '600',
                lineHeight: '1.3'
            }});
            text.innerText = label;

            row.appendChild(num);
            row.appendChild(text);
            overlay.appendChild(row);
        }});

        const divider = document.createElement('div');
        Object.assign(divider.style, {{
            width: '48px', height: '4px', backgroundColor: '#E63946',
            margin: '28px auto 0', borderRadius: '2px'
        }});
        overlay.appendChild(divider);

        document.body.appendChild(overlay);
        overlay.getBoundingClientRect();
        overlay.style.opacity = '1';
    }})();
    """
    page.evaluate(js_code)


def trigger_keypoint_transition(page: Page, excerpt: str, label: str, accent_color: str, kp_index: int, total_kps: int):
    """
    Batches ALL UI actions for a keypoint into a single JS execution to minimize latency.
    - Fades out previous highlight
    - Smooth-scrolls to new excerpt
    - Highlights with pulse animation
    - Injects lower-third with key point counter
    """
    js_code = f"""
    (async function() {{
        // 0. Inject shared CSS keyframe once
        if (!document.getElementById('atv-styles')) {{
            const style = document.createElement('style');
            style.id = 'atv-styles';
            style.textContent = `
                @keyframes atv-pulse {{
                    0%, 100% {{ transform: translateY(-4px); box-shadow: 0 8px 20px rgba(0,0,0,0.5), 0 3px 8px rgba(0,0,0,0.3); }}
                    50%       {{ transform: translateY(-7px); box-shadow: 0 14px 30px rgba(0,0,0,0.6), 0 4px 12px rgba(0,0,0,0.35); }}
                }}
                mark[data-atv-highlighted="true"] {{
                    display: inline-block;
                    position: relative;
                    padding: 4px 8px !important;
                    border-radius: 5px !important;
                    transform: translateY(-4px);
                    box-shadow: 0 8px 20px rgba(0,0,0,0.5), 0 3px 8px rgba(0,0,0,0.3);
                    animation: atv-pulse 1.6s ease-in-out infinite;
                    z-index: 10;
                }}
            `;
            document.head.appendChild(style);
        }}

        // 1. Fade out previous highlight
        document.querySelectorAll('mark[data-atv-highlighted="true"]').forEach(mark => {{
            mark.style.transition = 'opacity 0.25s ease';
            mark.style.opacity = '0';
            setTimeout(() => {{
                const parent = mark.parentNode;
                if (parent) {{
                    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
                    parent.removeChild(mark);
                    parent.normalize();
                }}
            }}, 250);
        }});
        const existingLT = document.getElementById('atv-lower-third');
        if (existingLT) {{
            existingLT.style.transform = 'translateX(-100%)';
            setTimeout(() => existingLT.remove(), 400);
        }}

        // 2. Scroll + Highlight
        const excerpt = {json.dumps(excerpt)};
        const accentColor = {json.dumps(accent_color)};

        let targetEl = null;
        let absoluteY = 0;
        const initialScrollY = window.scrollY;

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

        // 3. Inject lower-third with counter
        const label = {json.dumps(label)};
        const kpIndex = {kp_index};
        const totalKps = {total_kps};

        const lt = document.createElement('div');
        lt.id = 'atv-lower-third';
        lt.innerHTML = `
            <div style="width:6px; background-color:${{accentColor}}; border-radius:0 3px 3px 0; flex-shrink:0;"></div>
            <div style="display:flex; flex-direction:column; min-width:0;">
                <div style="background-color:rgba(0,0,0,0.88); padding:7px 20px 5px 14px; color:white; font-size:11px; font-weight:700; letter-spacing:3px; text-transform:uppercase; display:flex; justify-content:space-between; align-items:center; gap:16px;">
                    <span>KEY POINT</span>
                    <span style="color:${{accentColor}}; font-size:13px; letter-spacing:1px;">${{kpIndex}}&thinsp;/&thinsp;${{totalKps}}</span>
                </div>
                <div style="background-color:${{accentColor}}; padding:5px 20px 7px 14px; color:white; font-size:14px; font-weight:600; letter-spacing:0.3px; margin-top:2px;">${{label}}</div>
            </div>
        `;
        Object.assign(lt.style, {{
            position: 'fixed', bottom: '80px', left: '0', display: 'flex', alignItems: 'stretch',
            zIndex: '2147483647', fontFamily: 'Arial, sans-serif',
            transform: 'translateX(-100%)', transition: 'transform 0.5s cubic-bezier(0.22, 1, 0.36, 1)',
            maxWidth: '90%'
        }});
        document.body.appendChild(lt);
        lt.getBoundingClientRect();
        lt.style.transform = 'translateX(0)';
    }})();
    """
    page.evaluate(js_code)
