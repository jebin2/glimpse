# Article-to-Video Generator

A Python CLI tool that takes an article URL and outputs a 1080x1920 portrait MP4 video. It renders the article in a headless mobile browser, extracts a narration script via Gemini API, synthesizes speech via a custom Hugging Face TTS space, captures frames while smoothly scrolling, and multiplexes the audio into an MP4 file using FFmpeg.

## Prerequisites
- Python 3.10+
- `ffmpeg` installed on your system (`sudo apt install ffmpeg` or `brew install ffmpeg`)
- Chromium installed via Playwright

## Setup
1. Use an active virtual environment (e.g. `pyenv`).
2. Install dependencies:
   ```bash
   pip install git+https://github.com/jebin2/browser_manager.git
   pip install -r requirements.txt
   playwright install chromium
   ```
3. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
4. Get a [Gemini API Key](https://aistudio.google.com/) and place it in the `.env` file for `GEMINI_API_KEY`.

## Usage
Run the CLI passing in your article URL:
```bash
python main.py https://example.com/article
```
Optional arguments:
- `--output custom_name.mp4`: Save to a specific file.
- `--keep-temp`: Keeps the `frame_*.png` and `.wav` files inside the `/tmp/atv_slug` folder for debugging.

## Troubleshooting
| Error | Context | Fix |
|---|---|---|
| `ffmpeg not found` | Assembling video | Ensure `ffmpeg` is installed and in your PATH. |
| `Article appears paywalled...` | Downloading source | Run on an article accessible without a login or heavy JS blockers. |
| `KeyError: GEMINI_API_KEY` | Analyzing script | Validate `.env` is loaded and key is valid. |
| `HF API TTS Failed` | Creating Audio | Check your HF custom space or ensure server isn't down. |
