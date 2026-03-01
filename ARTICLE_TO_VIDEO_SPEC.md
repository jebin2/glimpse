# Article-to-Video Generator — Technical Specification

> **Purpose:** This document is the complete reference for building the `article-to-video` CLI tool. It is written for a developer or LLM agent to implement from scratch with no ambiguity.

---

## 1. Project Overview

A Python CLI tool that takes an article URL and outputs a 9:16 vertical MP4 video (1080×1920). The video shows the article rendered in a mobile browser viewport, smoothly scrolling through it while a TTS narrator reads a flowing AI-generated summary. As each key point is mentioned in the narration, the browser scrolls to and highlights the corresponding section of the article, staying highlighted for exactly as long as that segment is being spoken.

---

## 2. Final Output Spec

| Property | Value |
|---|---|
| Resolution | 1080 × 1920 (9:16 vertical) |
| FPS | 30 |
| Format | MP4 (H.264 video, AAC audio) |
| Audio | Mono or stereo, 22050–44100 Hz |
| Filename | `output_<sanitized_url_slug>.mp4` |

---

## 3. Tech Stack

| Component | Tool | Notes |
|---|---|---|
| Language | Python 3.10+ | |
| Browser automation | Playwright (Python) | `playwright install chromium` required |
| AI summarization | Gemini API (`gemini-2.5-flash`) | Via `google-generativeai` SDK |
| Text-to-speech | HuggingFace Inference API | Model configurable via `.env` |
| Video assembly | FFmpeg (subprocess) | Must be installed on system |
| Config | `python-dotenv` | `.env` file |
| Audio duration | `pydub` or `mutagen` | For measuring TTS segment lengths |

---

## 4. Project File Structure

```
article-to-video/
├── main.py               # CLI entry point + pipeline orchestrator
├── scraper.py            # Playwright: render, scroll, highlight, capture frames
├── ai_analysis.py        # Gemini: generate narration script + key point metadata
├── tts.py                # HuggingFace TTS: generate audio per segment
├── video.py              # FFmpeg: assemble frames + audio → MP4
├── utils.py              # Shared helpers (slugify, file cleanup, timing math)
├── .env                  # Secret keys (gitignored)
├── .env.example          # Template for .env
├── requirements.txt      # Python dependencies
└── README.md             # Usage instructions
```

---

## 5. Configuration (`.env`)

```dotenv
GEMINI_API_KEY=your_gemini_api_key_here,your_gemini_api_key_here,your_gemini_api_key_here
HF_API_KEY=your_huggingface_api_key_here
TTS_MODEL=facebook/mms-tts-eng
```

`.env.example` must mirror this exactly with placeholder values.

---

## 6. CLI Interface (`main.py`)

### Usage
```bash
python main.py <article_url> [--output output.mp4] [--keep-temp]
```

### Arguments
| Argument | Required | Default | Description |
|---|---|---|---|
| `article_url` | Yes | — | Full URL of the article to process |
| `--output` | No | `output_<slug>.mp4` | Output file path |
| `--keep-temp` | No | False | Keep `/tmp/atv_<slug>/` working directory after completion |

### Exit Codes
| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Article fetch/render failed (paywall, JS error, timeout) |
| 2 | Gemini API error |
| 3 | TTS API error |
| 4 | FFmpeg error |

### Console Output (stdout)
The CLI should print progress at each major step:
```
[1/5] Rendering article in mobile browser...
[2/5] Extracting key points with Gemini...
[3/5] Generating TTS audio (7 segments)...
[4/5] Capturing video frames...
[5/5] Assembling final video...
Done! → output_example-com-article.mp4 (45.2s)
```

---

## 7. Pipeline — Step-by-Step

The pipeline runs in **4 sequential passes**. Each pass depends on the output of the previous.

### Pass 1 — Article Rendering (`scraper.py`)

1. Launch Playwright Chromium in headless mode.
2. Set viewport to **390 × 844** (iPhone 14 Pro mobile).
3. Set `user_agent` to a real iPhone Safari UA string.
4. Navigate to the URL with a 30-second timeout.
5. Wait for `networkidle` (or `domcontentloaded` + 2s delay as fallback).
6. **Paywall/error detection:** If page title contains "404", "Access Denied", "Subscribe", or body text is under 200 characters, raise a `ScraperError` with a descriptive message and exit code 1.
7. Extract full page height via `document.body.scrollHeight`.
8. Take a **full-page screenshot** at this point (before any highlighting) for reference — save as `<tmpdir>/page_reference.png`.
9. Return a `PageContext` object:
   ```python
   @dataclass
   class PageContext:
       page: playwright.Page       # Keep browser open for Pass 3
       full_height: int            # Total scrollable height in px
       viewport_height: int = 844
   ```

---

### Pass 2 — AI Analysis (`ai_analysis.py`)

**Input:** The article's full text content (extracted from page via `page.inner_text('body')` after Pass 1).

**Gemini prompt** (send as a single user message):

```
You are a video script writer. Given the article text below, produce a JSON response with this exact structure:

{
  "narration_script": "A flowing 60-90 second summary of the article written as spoken narration. The script should naturally mention each key point as it comes up. Use conversational language suitable for TTS.",
  "key_points": [
    {
      "id": 1,
      "label": "Short title of this key point (5 words max)",
      "excerpt": "An exact verbatim quote (10-30 words) from the article that represents this key point. This will be used to locate the text in the DOM.",
      "script_anchor": "The exact phrase from narration_script that introduces this key point. This will be used for timing sync.",
      "position_hint": "early | middle | late"
    }
  ]
}

Rules:
- 5 to 7 key points total
- key_points must appear in the order they occur in the article
- excerpt must be verbatim text from the article (used for DOM search)
- script_anchor must be a substring that exists in narration_script
- Return only valid JSON, no markdown fences

Article text:
{article_text}
```

**Response parsing:**
- Strip any accidental markdown fences before `json.loads()`
- Validate that `script_anchor` for each key point is a substring of `narration_script`
- Validate that `len(key_points)` is between 5 and 7
- On validation failure: retry Gemini once. On second failure: exit with code 2.

**Output:** A `NarrationPlan` dataclass:
```python
@dataclass
class KeyPoint:
    id: int
    label: str
    excerpt: str          # verbatim article quote for DOM search
    script_anchor: str    # phrase in narration that triggers this highlight
    position_hint: str    # "early" | "middle" | "late"

@dataclass
class NarrationPlan:
    full_script: str      # complete narration text
    key_points: list[KeyPoint]
```

---

### Pass 3 — TTS Audio Generation (`tts.py`)

**Goal:** Split the narration script into segments timed to key points, generate one audio file per segment, measure each file's duration in seconds.

#### Script Segmentation

Split `full_script` into `N+1` segments using `script_anchor` values as split points, where N = number of key points.

Algorithm:
```python
segments = []
remaining = full_script
for kp in key_points:
    idx = remaining.find(kp.script_anchor)
    if idx == -1:
        raise ValueError(f"Anchor not found: {kp.script_anchor}")
    # Text before this anchor = previous segment
    pre = remaining[:idx].strip()
    if pre:
        segments.append({"type": "bridge", "text": pre, "key_point_id": None})
    # The anchor text itself starts a key point segment — extend to next anchor or end
    # Find end of this key point's coverage (to next anchor)
    next_anchors = [k.script_anchor for k in key_points[key_points.index(kp)+1:]]
    end_idx = len(remaining)
    for na in next_anchors:
        ni = remaining.find(na, idx)
        if ni != -1:
            end_idx = ni
            break
    kp_text = remaining[idx:end_idx].strip()
    segments.append({"type": "key_point", "text": kp_text, "key_point_id": kp.id})
    remaining = remaining[end_idx:]
if remaining.strip():
    segments.append({"type": "bridge", "text": remaining.strip(), "key_point_id": None})
```

#### TTS API Call

For each segment, call the HuggingFace Inference API:

```python
import requests

def generate_audio(text: str, output_path: str, hf_token: str, model: str) -> float:
    """Returns duration in seconds."""
    url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {"Authorization": f"Bearer {hf_token}"}
    payload = {"inputs": text}
    
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    
    with open(output_path, "wb") as f:
        f.write(response.content)
    
    # Measure duration
    from pydub import AudioSegment
    audio = AudioSegment.from_file(output_path)
    return len(audio) / 1000.0  # ms → seconds
```

**Retry logic:** On HTTP 503 (model loading), wait 20 seconds and retry up to 3 times. On other errors, exit with code 3.

**Output:** List of `AudioSegment` objects:
```python
@dataclass
class AudioSegmentInfo:
    segment_index: int
    type: str              # "bridge" or "key_point"
    key_point_id: int | None
    audio_path: str        # path to .flac or .wav file
    duration_seconds: float
    text: str
```

**Also produce:** A concatenated full narration audio file (`<tmpdir>/narration_full.wav`) by joining all segments in order using `pydub`. This is used as the final video audio track.

---

### Pass 4 — Frame Capture (`scraper.py`)

**Input:** `PageContext` (browser still open from Pass 1), `NarrationPlan`, `List[AudioSegmentInfo]`

**Goal:** Capture screenshot frames at 30fps for each segment's duration, scrolling the page and highlighting the relevant DOM element.

#### Scroll Position Calculation

For each key point, find the DOM element to scroll to:
```javascript
// Injected via page.evaluate()
function findElementByExcerpt(excerpt) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while (node = walker.nextNode()) {
        if (node.textContent.includes(excerpt.substring(0, 50))) {
            return node.parentElement;
        }
    }
    return null;
}
```

Get scroll target Y position:
```javascript
const el = findElementByExcerpt(excerpt);
if (el) {
    const rect = el.getBoundingClientRect();
    return window.scrollY + rect.top - 100; // 100px padding from top
}
return null;
```

#### Frame Capture Loop

For each `AudioSegmentInfo` in order:

```python
def capture_segment_frames(page, segment, scroll_target_y, tmpdir, frame_counter):
    fps = 30
    duration = segment.duration_seconds
    total_frames = int(duration * fps)
    
    # If this is a key_point segment: highlight + scroll
    if segment.type == "key_point":
        # Inject highlight
        page.evaluate(f"""
            (function() {{
                const el = findElementByExcerpt({json.dumps(excerpt)});
                if (el) {{
                    el.style.backgroundColor = '#FFE066';
                    el.style.transition = 'background-color 0.3s ease';
                    el._atv_highlighted = true;
                }}
            }})()
        """)
        
        # Smooth scroll to element
        page.evaluate(f"window.scrollTo({{top: {scroll_target_y}, behavior: 'smooth'}})")
        time.sleep(0.4)  # Allow scroll animation to settle
    
    # Capture frames
    for i in range(total_frames):
        screenshot_path = f"{tmpdir}/frame_{frame_counter:06d}.png"
        page.screenshot(path=screenshot_path, clip={
            "x": 0, "y": page.evaluate("window.scrollY"),
            "width": 390,
            "height": 844
        })
        # Note: For scrolling segments, update scrollY between frames if needed
        frame_counter += 1
        time.sleep(1 / fps)
    
    # De-highlight after segment
    if segment.type == "key_point":
        page.evaluate("""
            document.querySelectorAll('[data-atv-highlighted]').forEach(el => {
                el.style.backgroundColor = '';
            });
        """)
    
    return frame_counter
```

> **Important:** For `bridge` segments (no highlight), the page should continue scrolling slowly and naturally downward at a pace of approximately `full_height / total_video_duration * segment_duration` pixels per second.

#### Progress Pill Overlay

After each screenshot is taken, overlay a progress pill using Pillow **before** saving the frame to disk:

```python
from PIL import Image, ImageDraw, ImageFont

def add_progress_pill(img_path: str, current: int, total: int):
    """
    Draws a pill in the top-right corner of the frame.
    Style: rounded rectangle, semi-transparent dark background, white text.
    Position: 12px from top, 12px from right edge.
    Size: auto-sized to text content.
    Font: Bold, 18px.
    Format: "2 / 7"
    Only shown during key_point segments (not bridge segments).
    """
    img = Image.open(img_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    text = f"{current} / {total}"
    # Load font — fallback to default if custom not available
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except:
        font = ImageFont.load_default()
    
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    pad_x, pad_y = 12, 6
    pill_w = text_w + pad_x * 2
    pill_h = text_h + pad_y * 2
    
    x = img.width - pill_w - 12
    y = 12
    
    # Draw rounded rect (dark semi-transparent)
    draw.rounded_rectangle([x, y, x + pill_w, y + pill_h], radius=pill_h//2, fill=(0, 0, 0, 180))
    draw.text((x + pad_x, y + pad_y), text, font=font, fill=(255, 255, 255, 255))
    
    combined = Image.alpha_composite(img, overlay).convert("RGB")
    combined.save(img_path)
```

Progress pill is only shown when `segment.type == "key_point"`. The pill shows the key point number (1-indexed) out of total key points.

---

### Pass 5 — Video Assembly (`video.py`)

**Input:** Directory of frames (`frame_000000.png` ... `frame_NNNNNN.png`), `narration_full.wav`

**FFmpeg command:**

```python
import subprocess

def assemble_video(frames_dir: str, audio_path: str, output_path: str):
    cmd = [
        "ffmpeg", "-y",
        # Input: image sequence at 30fps
        "-framerate", "30",
        "-i", f"{frames_dir}/frame_%06d.png",
        # Input: audio
        "-i", audio_path,
        # Video filter: scale 390px wide to 1080px wide, pad to 1920 tall with black bars
        "-vf", "scale=1080:-2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        # Video codec
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        # Audio codec
        "-c:a", "aac",
        "-b:a", "128k",
        # Sync: use shortest stream (in case audio is slightly longer)
        "-shortest",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise VideoAssemblyError(f"FFmpeg failed:\n{result.stderr}")
```

> **Scale logic:** The 390px mobile viewport is scaled up to 1080px wide (2.769× scale). At 844px tall, the scaled height = 2338px, which is taller than 1920. The `-2` in `scale=1080:-2` preserves aspect ratio. If height > 1920, crop vertically centered: use `-vf "scale=1080:-2,crop=1080:1920:0:(ih-1920)/2"`. If height < 1920, pad with black bars.

---

## 8. Temporary File Layout

All intermediate files go in `/tmp/atv_<slug>/`:

```
/tmp/atv_example-com-article/
├── page_reference.png          # Full-page screenshot (reference only)
├── audio_seg_000.wav           # TTS segment 0 (bridge before first key point)
├── audio_seg_001.wav           # TTS segment 1 (key point 1)
├── audio_seg_002.wav           # ...
├── narration_full.wav          # Concatenated full audio
├── frame_000000.png            # Video frames
├── frame_000001.png
├── ...
└── frame_NNNNNN.png
```

Cleaned up automatically unless `--keep-temp` is passed.

---

## 9. Error Handling

| Scenario | Behavior |
|---|---|
| URL times out (30s) | Print: `ERROR: Could not load article (timeout). Is the URL accessible?` → exit 1 |
| Paywall/short content detected | Print: `ERROR: Article appears paywalled or has no readable content.` → exit 1 |
| Gemini returns invalid JSON | Retry once. On second failure: print error + exit 2 |
| HF TTS returns 503 | Wait 20s, retry up to 3 times. Print: `Waiting for TTS model to load...` |
| HF TTS returns 4xx | Print: `ERROR: TTS API rejected request (check HF_API_KEY and TTS_MODEL in .env)` → exit 3 |
| `script_anchor` not found in script | Retry Gemini. If still broken: skip that key point (log warning), continue |
| DOM element not found for excerpt | Log warning: `Warning: Could not locate text for key point N in DOM. Skipping highlight.` Continue without highlight |
| FFmpeg not installed | Print: `ERROR: ffmpeg not found. Install with: brew install ffmpeg` → exit 4 |

---

## 10. Highlight Style

Injected via `page.evaluate()`. Applied directly to the DOM element containing the excerpt text.

```javascript
el.style.backgroundColor = '#FFE066';  // Bright yellow
el.style.borderRadius = '3px';
el.style.transition = 'background-color 0.3s ease';
```

De-highlight (end of segment):
```javascript
el.style.backgroundColor = '';
el.style.borderRadius = '';
```

---

## 11. `requirements.txt`

```
playwright>=1.40.0
google-generativeai>=0.5.0
requests>=2.31.0
pydub>=0.25.1
mutagen>=1.47.0
Pillow>=10.0.0
python-dotenv>=1.0.0
```

System dependencies (not pip):
- `ffmpeg` (installed via package manager)
- `chromium` (installed via `playwright install chromium`)

---

## 12. `README.md` Contents

Must include:
1. Prerequisites (Python 3.10+, ffmpeg, playwright install chromium)
2. Setup steps (`pip install -r requirements.txt`, copy `.env.example` → `.env`, fill keys)
3. Usage example: `python main.py https://example.com/article`
4. How to get a Gemini API key (link: https://aistudio.google.com)
5. How to get a HuggingFace API key (link: https://huggingface.co/settings/tokens)
6. Troubleshooting table (common errors + fixes)

---

## 13. Key Design Decisions & Rationale

| Decision | Rationale |
|---|---|
| Python over Node | Cleaner Gemini SDK, better pydub/Pillow ecosystem for audio/image processing. Playwright Python is production-ready. |
| Two-pass (audio before frames) | TTS duration must be known before frame capture so scroll timing is audio-driven, not guessed |
| Pillow for progress pill | Avoids FFmpeg drawtext complexity; more precise control over pill rendering per-frame |
| `script_anchor` substring matching | Allows Gemini to define exactly where in the narration each key point occurs, enabling precise sync without word timestamps |
| `networkidle` wait + fallback | Some articles load content via JS; `networkidle` catches this. Fallback prevents hanging on sites that never reach idle |
| `page.screenshot` with clip | Captures only the current viewport region (390×844) rather than full page, matching what a user would see while scrolling |
| Highlight via DOM injection not FFmpeg | Playwright JS injection is accurate to DOM elements; no coordinate mapping needed between browser and video resolution |

---

## 14. Known Limitations

- **Paywalled articles:** Detected and rejected gracefully. No bypass attempted.
- **SPAs / infinite scroll:** May not capture all content. `networkidle` handles most cases.
- **Long articles:** TTS generation time scales linearly with narration length. A 90-second narration = ~7 API calls, typically 15–30s total TTS wait.
- **HuggingFace cold starts:** Free tier models may take 20–40s to warm up on first call.
- **Font availability:** Progress pill falls back to PIL default font if DejaVu not installed. Can look pixelated. Consider bundling a `.ttf` file.
- **Dynamic highlight targets:** If the article reflows (e.g. lazy-loaded images shift DOM), scroll targets may be slightly off. Consider using `page.wait_for_load_state('networkidle')` before calculating scroll positions.

---

*Spec version: 1.0 | Last updated: 2026-03-01*
