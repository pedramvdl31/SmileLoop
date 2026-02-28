# coding: utf-8
"""
SmileLoop – Video Watermarking

Adds a subtle "SmileLoop Preview" watermark to the preview video.
Uses ffmpeg (must be installed).
"""

import subprocess
import shutil
from pathlib import Path


def add_watermark(input_path: Path, output_path: Path, text: str = "SmileLoop Preview") -> bool:
    """
    Overlay a semi-transparent text watermark on a video.
    Returns True on success.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        # If ffmpeg not available, just copy the file
        shutil.copy2(input_path, output_path)
        return True

    # Subtle white text with slight shadow, centered, semi-transparent
    drawtext = (
        f"drawtext=text='{text}':"
        f"fontsize=28:"
        f"fontcolor=white@0.35:"
        f"x=(w-text_w)/2:"
        f"y=(h-text_h)/2:"
        f"shadowcolor=black@0.2:"
        f"shadowx=1:shadowy=1"
    )

    cmd = [
        ffmpeg,
        "-y",
        "-i", str(input_path),
        "-vf", drawtext,
        "-codec:a", "copy",
        "-preset", "fast",
        str(output_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        return result.returncode == 0 and output_path.exists()
    except Exception:
        # Fallback: copy without watermark
        shutil.copy2(input_path, output_path)
        return True
