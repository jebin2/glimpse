from jebin_lib import load_env
load_env()

import argparse
import os
import random
import glob as glob_module

import jebin_lib.merge_audio as merge_audio
from jebin_lib import normalize_loudness
from glimpse.core.scraper import Scraper
from glimpse.core.ai_analysis import AIAnalyzer
from glimpse.core.tts_manager import TTSManager
from glimpse.core.video_assembler import VideoAssembler
from glimpse.utils.helpers import slugify, cleanup_tmp_dir, Timer, format_time
from custom_logger import logger_config

def main():
    parser = argparse.ArgumentParser(description="Article-to-Video CLI Generator")
    parser.add_argument("article_url", type=str, help="Full URL of the article to process")
    parser.add_argument("--output", type=str, default="", help="Output MP4 file path")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary directory after completion")
    parser.add_argument("--test", action="store_true", help="Use cached test data instead of live API calls")
    args = parser.parse_args()

    import time
    timestamp = str(int(time.time()))
    slug = slugify(args.article_url)
    output_path = args.output if args.output else f"output_{slug}.mp4"
    tmpdir = f"/tmp/atv_{slug}_{timestamp}"
    
    os.makedirs(tmpdir, exist_ok=True)
    try:
        os.chmod(tmpdir, 0o777) # Ensure Docker container user can write WebM here
    except PermissionError:
        logger_config.warning(f"Could not chmod {tmpdir}. Will try to continue anyway.")
    
    logger_config.info(f"--- Article-to-Video Workflow ---")
    logger_config.info(f"URL: {args.article_url}")
    logger_config.info(f"Temp Dir: {tmpdir}")
    logger_config.info(f"Will output to: {output_path}")
    
    scraper = Scraper(headless=True)
    ai = AIAnalyzer(test=args.test)
    tts = TTSManager(test=args.test)
    assembler = VideoAssembler()
    
    with Timer() as full_timer:
        try:
            # PASS 1: Fetch article & Start Session
            page, body_text = scraper.start_session(args.article_url, tmpdir)
            
            # PASS 2: GenAI Scripting
            narration_plan = ai.extract_plan(body_text)
            logger_config.info(f"Got script with {len(narration_plan.key_points)} key points.")
            
            # PASS 3: TTS
            audio_path, audio_segments = tts.generate_all(narration_plan, tmpdir)
            
            # PASS 3.5: Merge background music
            bg_music_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glimpse", "bg_music")
            bg_files = glob_module.glob(os.path.join(bg_music_dir, "*.*"))
            if bg_files:
                bg_path = random.choice(bg_files)
                merged_path = os.path.join(tmpdir, "narration_with_bg.wav")
                logger_config.info(f"Merging bg music: {os.path.basename(bg_path)}")
                merge_audio.process(audio_path, bg_path, merged_path)
                audio_path = merged_path
            else:
                logger_config.warning("No bg music files found, skipping merge.")

            # PASS 4: Scraper Precision Recording
            logger_config.info("Pipeline Step 4: Video Scraper")
            pass_wall_time = scraper.record_video_pass(page, narration_plan, audio_segments)
            
            # Stop the browser session to finalize the .webm file
            scraper.stop_session(page)
            
            # Now we can find the finalized webm file
            import glob
            webm_files = glob.glob(os.path.join(tmpdir, "*.webm"))
            if not webm_files:
                raise RuntimeError("Playwright failed to generate a .webm file.")
            webm_path = max(webm_files, key=os.path.getctime)
            
            # Calculate exact trim offset from the END of the video:
            # The recording pass (top-of-page → cleanup) occupies the last
            # pass_wall_time seconds of the .webm.  Everything before that
            # is page-load / setup footage we want to skip.
            video_duration = assembler.get_video_duration(webm_path)
            start_offset = max(0, video_duration - pass_wall_time)
            logger_config.info(f"Video duration: {video_duration:.2f}s | Pass wall time: {pass_wall_time:.2f}s | Trim offset: {start_offset:.2f}s")
            
            # Pass 5: Assemble Video
            logger_config.info("Pipeline Step 5: Final Assembly")
            if not audio_path or not os.path.exists(audio_path):
                audio_path = os.path.join(tmpdir, "narration_full.wav")
                
            total_duration = audio_segments[-1].end_time if audio_segments else 0
            assembler.assemble_video(webm_path, audio_path, output_path, total_duration, start_offset)

            # PASS 6: Loudness normalization (EBU R128, -14 LUFS for YouTube Shorts)
            normalize_loudness(output_path)

            logger_config.success(f"Done! -> {output_path} (Took {format_time(full_timer.duration)})")
            
        finally:
            # Cleanup
            if not args.keep_temp:
                cleanup_tmp_dir(tmpdir)

if __name__ == "__main__":
    main()
