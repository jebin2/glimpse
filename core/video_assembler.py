import subprocess
import os
from custom_logger import logger_config
import glob

class VideoAssembler:
    @staticmethod
    def get_video_duration(video_path: str) -> float:
        """Use ffprobe to get the exact duration of a video file in seconds."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger_config.error(f"ffprobe failed: {result.stderr}")
            return 0.0
        return float(result.stdout.strip())


    def assemble_video(self, webm_path: str, audio_path: str, output_path: str, duration: float, start_offset: float = 0.0):
        """
        Pass 5: Take the raw `.webm` and mux it with `audio_path`.
        Uses precise start-time seeking (-ss) to bypass the loading phase.
        """
        logger_config.info(f"[5/5] Assembling final video (seeking to {start_offset:.2f}s, duration {duration:.2f}s)...")
        
        # Check if ffmpeg exists
        if subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0:
            logger_config.error("ffmpeg not found.")
            exit(4)
            
        cmd = [
            "ffmpeg", "-y",
            "-i", webm_path,
            "-i", audio_path,
            # Precise Filter-based trimming to avoid keyframe snapping issues in WebM
            "-filter_complex", (
                f"[0:v]trim=start={start_offset}:duration={duration},"
                f"setpts=PTS-STARTPTS,"
                f"fps=30,scale=1080:1920:force_original_aspect_ratio=decrease,"
                f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black[v]"
            ),
            "-map", "[v]",
            "-map", "1:a",
            # Codecs
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", 
            output_path
        ]
        
        # We don't have individual frame numbers to easily parse from a variable-framerate webm 
        # so we will just run subprocess synchronously like before as it finishes in ~3 seconds anyway
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger_config.error("VideoAssemblyError: FFmpeg failed:")
            logger_config.error(result.stderr)
            exit(4)
