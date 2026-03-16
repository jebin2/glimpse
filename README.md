# Glimpse

Converts any news article URL into a 1080×1920 portrait MP4 video — ready for YouTube Shorts, TikTok, or Instagram Reels.

Glimpse renders the article in a headless mobile browser, writes a broadcast-style narration script via Gemini, synthesises speech via a Hugging Face TTS space, records the browser scrolling in sync with the narration, and assembles everything with FFmpeg. Each key point in the script triggers a smooth scroll, a pulsing text highlight, and an animated lower-third overlay with a live progress bar and article headline hook.

## Pipeline

```
[1] Browser session    — load article, apply site handlers
[2] AI scripting       — Gemini extracts narration script + key points
[3] TTS + STT          — generate speech, transcribe for word-level timing
[3.5] BG music merge   — pick random track from bg_music/, auto-balance levels
[4] Video recording    — sync scroll/highlight/overlays to audio timestamps
[5] Assembly           — FFmpeg mux: blurred background fill, H.264 output
[6] Loudness normalize — two-pass EBU R128 at -14 LUFS (YouTube Shorts standard)
```

## Prerequisites

- Python 3.10+
- Docker (for the headless browser container)
- `ffmpeg` installed system-wide (`sudo apt install ffmpeg`)

## Installation

```bash
git clone https://github.com/jebin2/glimpse.git
cd glimpse
pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and fill in:

```env
GEMINI_API_KEY=your_key_here   # https://aistudio.google.com/
```

## Usage

```bash
glimpse <article_url> [options]
```

**Options**

| Flag | Description |
|---|---|
| `--output path.mp4` | Custom output file path |
| `--keep-temp` | Retain `/tmp/atv_*` working directory after completion |
| `--test` | Use cached `test_data/` files — skips live API calls for fast iteration |

**Examples**

```bash
# Full run
glimpse https://www.bbc.co.uk/news/world

# Fast iteration using cached data
glimpse https://www.bbc.co.uk/news/resources/idt-259820d0-52f5-42b2-af79-bca71d9b0aba --test

# Custom output path
glimpse https://www.bbc.co.uk/news/world --output bbc_world.mp4
```

## Customising the Prompt

The default prompt in `glimpse/prompts/script_writer.md` is tuned for **news articles** — it writes in a broadcast anchor style with "BREAKING NEWS" framing.

If you are using Glimpse with a different type of content (blog posts, tutorials, product reviews, etc.), update the prompt to match the tone and structure of your content. Key things to change:

- The persona ("You are a professional news anchor…") — replace with the appropriate voice
- The narration style ("factual, authoritative") — match your content's tone
- The `key_points` guidance — adjust what counts as a meaningful highlight for your content type

The STT correction prompt (`glimpse/prompts/STT_spelling_corrector.md`) is content-agnostic and does not need changes.

## Background Music

Drop audio files (`.mp3`, `.wav`, etc.) into `glimpse/bg_music/`. A random track is selected per run, auto-mixed under the narration with loudness-aware volume balancing.

## Project Structure

```
glimpse/
  glimpse/
    core/
      ai_analysis.py      — Gemini scripting, NarrationPlan dataclass
      scraper.py          — browser session, recording pass
      page_actions.py     — JS overlays: headline card, progress bar, highlights, lower-third
      site_handlers.py    — per-site DOM cleanup
      tts_manager.py      — TTS generation, STT alignment
      video_assembler.py  — FFmpeg assembly + blurred background fill
    utils/
      helpers.py          — slugify, cleanup, Timer
    prompts/
      script_writer.md    — Gemini prompt for narration + key points
      STT_spelling_corrector.md — Gemini prompt for STT force-alignment
    bg_music/             — background music tracks
  main.py
  pyproject.toml
```

## Troubleshooting

| Error | Step | Fix |
|---|---|---|
| `ffmpeg not found` | Assembly | Install ffmpeg and ensure it is in PATH |
| `GEMINI_API_KEY not set` | AI scripting | Add key to `.env` |
| `HF API TTS failed` | TTS | Check your HF custom space is running |
| `Playwright failed to generate .webm` | Recording | Ensure Docker is running and the container can write to `/tmp` |
| `No bg music files found` | BG merge | Add at least one audio file to `glimpse/bg_music/` |
