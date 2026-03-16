import re
import os
import shutil
import time
from custom_logger import logger_config

def slugify(text: str) -> str:
    """Convert a string or URL to a URL-safe slug."""
    # Remove protocol
    text = re.sub(r'^https?://', '', text)
    # Remove special characters
    text = re.sub(r'[^a-zA-Z0-9]', '-', text)
    # Remove duplicate hyphens
    text = re.sub(r'-+', '-', text)
    # Remove leading/trailing hyphens
    text = text.strip('-')
    return text.lower()[:50]  # Keep reasonably short

def format_time(seconds: float) -> str:
    """Format seconds into a readable MM:SS.ms string."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{mins:02d}:{secs:02d}.{ms:03d}"

def cleanup_tmp_dir(tmpdir: str):
    """Safely remove a temporary directory and all its contents."""
    try:
        if os.path.exists(tmpdir):
            shutil.rmtree(tmpdir)
            logger_config.info(f"Cleaned up temporary directory: {tmpdir}")
    except Exception as e:
        logger_config.warning(f"Failed to clean up temporary directory {tmpdir}: {e}")

class Timer:
    """Simple context manager for timing operations."""
    def __enter__(self):
        self.start = time.perf_counter()
        self._end = None
        return self

    def __exit__(self, *args):
        self._end = time.perf_counter()

    @property
    def duration(self):
        if self._end is not None:
            return self._end - self.start
        return time.perf_counter() - self.start
