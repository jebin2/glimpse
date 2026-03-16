import os
import json
import time
from typing import Optional

from browser_manager import BrowserManager
from browser_manager.browser_config import BrowserConfig
from glimpse.core.page_actions import (
    find_and_highlight_element,
    remove_highlights,
    scroll_to_element,
    scroll_continuous,
    inject_lower_third,
    remove_lower_third,
    remove_ads,
    inject_headline_card,
    inject_progress_bar,
    inject_summary_card,
    trigger_keypoint_transition
)
from PIL import Image, ImageDraw, ImageFont
from glimpse.core.site_handlers import apply_site_handlers
from custom_logger import logger_config

class Scraper:
    def __init__(self, headless: bool = True):
        self.config = BrowserConfig(
            headless=headless,
            docker_name="glimpse_neko",
            browser_flags=(
                "--disable-gpu "
                "--no-sandbox --no-zygote --disable-extensions "
                "--window-size=540,960 --no-first-run "
                "--disable-session-crashed-bubble --disable-infobars "
                "--disable-dev-shm-usage --hide-scrollbars"
            )
        )
        self.manager = BrowserManager(self.config)

    def start_session(self, url: str, tmpdir: str) -> tuple[any, str]:
        """
        Starts the browser session and keeps it open.
        """
        logger_config.info(f"[1/5] Starting persistent browser session (Container: {self.config.docker_name})...")
        self.config.url = url
        self.config.additionl_docker_flag = f"-v {tmpdir}:{tmpdir} -e NEKO_DESKTOP_SCREEN=540x960@30"
        
        page = self.manager.start(record_video_dir=tmpdir, record_video_size={"width": 540, "height": 960})
        page.set_viewport_size({"width": 540, "height": 960})
        time.sleep(2)
        
        apply_site_handlers(page, url)
        # remove_ads(page)
        
        body_text = page.inner_text("body")
        return page, body_text

    def record_video_pass(self, page, narration_plan, audio_segments) -> float:
        """
        Executes the recording pass using the existing page.
        Returns the wall-clock duration of the pass (from scroll-to-top
        through cleanup).  The caller uses this together with the total
        video file duration (via ffprobe) to compute the trim offset:
            trim_start = video_file_duration - pass_wall_time
        """
        logger_config.info("[4/5] Executing high-precision recording pass...")
        
        # 1. Reset to Top of Page and Ensure Render
        page.evaluate("window.scrollTo(0, 0)")
        # Give it 500ms to ensure the scroll is applied and any dynamic headers settle
        time.sleep(0.5)
        
        # 2. Anchor — start the wall-clock stopwatch right when the page is
        #    at scroll position 0.  Everything from here until the end of this
        #    method is what the viewer should see in the final video.
        pass_start = time.perf_counter()

        logger_config.info("--- RECORDING PASS START (page at top) ---")

        total_duration_ms = (audio_segments[-1].end_time if audio_segments else 30) * 1000
        total_kps = len(narration_plan.key_points)

        # Inject hook overlay and progress bar at the very start of the recording
        inject_headline_card(page)
        inject_progress_bar(page, total_duration_ms)

        start_wall_time = time.perf_counter()
        lt_colors = ["#E63946"]
        color_idx = 0

        for segment in audio_segments:
            # Wait for segment start
            while (time.perf_counter() - start_wall_time) < segment.start_time:
                time.sleep(0.005)

            actual_start = time.perf_counter() - start_wall_time
            drift_ms = (actual_start - segment.start_time) * 1000

            duration = segment.end_time - segment.start_time
            flag = " ⚠ LONG" if duration > 8 else ""
            logger_config.info(
                f"[seg {segment.segment_index:02d}] {segment.type:<10} | "
                f"{segment.start_time:6.2f}s → {segment.end_time:6.2f}s | "
                f"dur: {duration:.2f}s{flag} | drift: {drift_ms:.1f}ms"
            )

            # Auto-scroll during long bridge segments to keep the video moving
            SCROLL_THRESHOLD = 4.0   # seconds
            SCROLL_SPEED     = 55.0  # px/s — comfortable reading pace
            if segment.type == "bridge" and duration > SCROLL_THRESHOLD:
                scroll_continuous(page, SCROLL_SPEED, duration)

            if segment.type == "key_point":
                kp = next((k for k in narration_plan.key_points if k.id == segment.key_point_id), None)
                if kp:
                    accent_color = lt_colors[color_idx % len(lt_colors)]
                    color_idx += 1
                    trigger_keypoint_transition(page, kp.excerpt, kp.label, accent_color, color_idx, total_kps)
            
            # Wait for segment end
            while (time.perf_counter() - start_wall_time) < segment.end_time:
                time.sleep(0.005)

        # Summary card — show all key points for 2s before fade-out
        remove_highlights(page)
        remove_lower_third(page)
        inject_summary_card(page, narration_plan.key_points)
        time.sleep(2.0)

        # Cleanup
        time.sleep(0.5)
        
        pass_wall_time = time.perf_counter() - pass_start
        logger_config.info(f"--- RECORDING PASS END (wall time: {pass_wall_time:.2f}s) ---")
        
        return pass_wall_time

    def stop_session(self, page):
        """Cleanly close the session and manager."""
        page.close()
        try:
            page.context.close()
        except:
            pass
        time.sleep(1)
        self.manager.stop()
