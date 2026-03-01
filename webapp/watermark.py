# coding: utf-8
"""
SmileLoop – Video Watermarking

Creates a watermarked preview from the full video.
Strategy: generate a transparent PNG watermark with Pillow, then
composite it onto the video using ffmpeg's overlay filter (which is
always available, unlike drawtext which requires --enable-libfreetype).

The watermark is large, bold, and tiled diagonally across the entire
frame so the preview cannot be used as a substitute for the paid version.

Falls back to a simple copy if ffmpeg/Pillow are not available.
"""

import math
import shutil
import subprocess
import tempfile
from pathlib import Path


def _create_watermark_png(width: int, height: int, text: str = "SmileLoop") -> Path | None:
    """Create a transparent PNG with large diagonal repeating watermark text."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Very large bold font — roughly 18% of the video width
        font_size = max(48, width // 5)
        font = None
        # Try bold fonts first
        bold_fonts = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFCompact.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        for fpath in bold_fonts:
            try:
                font = ImageFont.truetype(fpath, font_size)
                break
            except (OSError, IOError):
                continue
        if font is None:
            font = ImageFont.load_default()

        # Measure single text instance
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        # We'll draw on a larger canvas, rotated -30 degrees, then crop
        # Diagonal dimension to cover corners when rotated
        diag = int(math.sqrt(width ** 2 + height ** 2))
        tile_img = Image.new("RGBA", (diag * 2, diag * 2), (0, 0, 0, 0))
        tile_draw = ImageDraw.Draw(tile_img)

        # Very dense spacing — maximum coverage
        x_spacing = tw + max(10, width // 30)
        y_spacing = th + max(10, height // 16)

        # Draw text with dark outline first, then white fill on top
        # High opacity so watermark is unmissable
        outline_color = (0, 0, 0, 140)
        fill_color = (255, 255, 255, 220)
        outline_offset = max(3, font_size // 20)

        for y in range(0, diag * 2, y_spacing):
            for x in range(0, diag * 2, x_spacing):
                # Dark stroke / outline
                for dx in range(-outline_offset, outline_offset + 1):
                    for dy in range(-outline_offset, outline_offset + 1):
                        if dx == 0 and dy == 0:
                            continue
                        tile_draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
                # White text on top
                tile_draw.text((x, y), text, font=font, fill=fill_color)

        # Rotate -30 degrees
        rotated = tile_img.rotate(30, resample=Image.BICUBIC, expand=False)

        # Crop center to original video dimensions
        cx, cy = rotated.width // 2, rotated.height // 2
        left = cx - width // 2
        top = cy - height // 2
        cropped = rotated.crop((left, top, left + width, top + height))

        # Save to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        cropped.save(tmp.name, "PNG")
        return Path(tmp.name)

    except ImportError:
        print("WARNING: Pillow not available — cannot create watermark image.")
        return None
    except Exception as e:
        print(f"WARNING: Failed to create watermark image: {e}")
        import traceback; traceback.print_exc()
        return None


def _get_video_dimensions(video_path: Path) -> tuple[int, int]:
    """Get video width and height using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and "x" in result.stdout:
            w, h = result.stdout.strip().split("x")
            return int(w), int(h)
    except Exception:
        pass
    # Default fallback
    return 480, 480


def create_watermarked_preview(
    full_video_path: Path | str,
    preview_path: Path | str,
    text: str = "SmileLoop",
) -> bool:
    """
    Create a watermarked preview video.

    Args:
        full_video_path: Path to the unwatermarked full video.
        preview_path: Where to write the watermarked preview.
        text: Watermark text to overlay.

    Returns:
        True if watermarked successfully, False if fell back to copy.
    """
    full_video_path = Path(full_video_path)
    preview_path = Path(preview_path)
    preview_path.parent.mkdir(parents=True, exist_ok=True)

    if not shutil.which("ffmpeg"):
        print("WARNING: ffmpeg not found — copying full video as preview (no watermark).")
        shutil.copy2(full_video_path, preview_path)
        return False

    # Get video dimensions
    width, height = _get_video_dimensions(full_video_path)

    # Create watermark PNG overlay
    wm_path = _create_watermark_png(width, height, text)
    if not wm_path:
        print("WARNING: Could not create watermark overlay — copying full video.")
        shutil.copy2(full_video_path, preview_path)
        return False

    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(full_video_path),
            "-i", str(wm_path),
            "-filter_complex", "[0:v][1:v]overlay=0:0[out]",
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(preview_path),
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            print(f"WARNING: ffmpeg overlay failed (rc={result.returncode}): {result.stderr[:300]}")
            shutil.copy2(full_video_path, preview_path)
            return False

        return True

    except subprocess.TimeoutExpired:
        print("WARNING: ffmpeg watermark timed out — copying full video as preview.")
        shutil.copy2(full_video_path, preview_path)
        return False
    except Exception as e:
        print(f"WARNING: ffmpeg watermark error: {e} — copying full video as preview.")
        shutil.copy2(full_video_path, preview_path)
        return False
    finally:
        # Clean up temp watermark image
        try:
            wm_path.unlink(missing_ok=True)
        except Exception:
            pass
