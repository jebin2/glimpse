import os
import json
import time
from dataclasses import dataclass
from typing import Optional

from browser_manager import BrowserManager
from browser_manager.browser_config import BrowserConfig
from core.page_actions import (
    find_and_highlight_element,
    remove_highlights,
    scroll_to_element,
    inject_lower_third,
    remove_lower_third,
    remove_ads,
    trigger_keypoint_transition
)
from PIL import Image, ImageDraw, ImageFont
from core.site_handlers import apply_site_handlers
from custom_logger import logger_config

@dataclass
class PageContext:
    manager: BrowserManager
    page: any # playwright Page
    full_height: int
    viewport_height: int = 667

class Scraper:
    def __init__(self, headless: bool = True):
        self.config = BrowserConfig(
            headless=headless,
            docker_name="glimpse_neko",
            extra_args=[
                "--window-size=375,667", 
                "--hide-scrollbars"
            ]
        )
        self.manager = BrowserManager(self.config)

    def start_session(self, url: str, tmpdir: str) -> tuple[any, str]:
        """
        Starts the browser session and keeps it open.
        """
        logger_config.info(f"[1/5] Starting persistent browser session (Container: {self.config.docker_name})...")
        self.config.url = url
        self.config.additionl_docker_flag = f"-v {tmpdir}:{tmpdir}"
        
        page = self.manager.start(record_video_dir=tmpdir, record_video_size={"width": 375, "height": 667})
        page.set_viewport_size({"width": 375, "height": 667})
        
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2) 
        
        apply_site_handlers(page, url)
        remove_ads(page)
        
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
        
        start_wall_time = time.perf_counter()
        lt_colors = ["#E63946", "#457B9D", "#2D6A4F"]
        color_idx = 0
        
        for segment in audio_segments:
            # Wait for segment start
            while (time.perf_counter() - start_wall_time) < segment.start_time:
                time.sleep(0.005)

            actual_start = time.perf_counter() - start_wall_time
            drift_ms = (actual_start - segment.start_time) * 1000
            
            if segment.type == "key_point":
                logger_config.debug(f"TRIGGER [{segment.segment_index}]: KP {segment.key_point_id} | Drift: {drift_ms:.1f}ms")
                kp = next((k for k in narration_plan.key_points if k.id == segment.key_point_id), None)
                if kp:
                    accent_color = lt_colors[color_idx % len(lt_colors)]
                    color_idx += 1
                    trigger_keypoint_transition(page, kp.excerpt, kp.label, accent_color, color_idx)
            
            # Wait for segment end
            while (time.perf_counter() - start_wall_time) < segment.end_time:
                time.sleep(0.005)

        # Cleanup
        remove_highlights(page)
        remove_lower_third(page)
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
