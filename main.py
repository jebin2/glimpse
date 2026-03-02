import argparse
import os
from dotenv import load_dotenv

from core.scraper import Scraper
from core.ai_analysis import AIAnalyzer
from core.tts_manager import TTSManager
from core.video_assembler import VideoAssembler
from utils.helpers import slugify, cleanup_tmp_dir, Timer, format_time
from custom_logger import logger_config

def main():
    parser = argparse.ArgumentParser(description="Article-to-Video CLI Generator")
    parser.add_argument("article_url", type=str, help="Full URL of the article to process")
    parser.add_argument("--output", type=str, default="", help="Output MP4 file path")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary directory after completion")
    args = parser.parse_args()
    
    # Load .env variables
    load_dotenv()
    
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
    ai = AIAnalyzer()
    tts = TTSManager()
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
            
            logger_config.success(f"Done! -> {output_path} (Took {format_time(full_timer.duration)})")
            
        finally:
            # Cleanup
            if not args.keep_temp:
                cleanup_tmp_dir(tmpdir)

if __name__ == "__main__":
    main()
