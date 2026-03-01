#!/usr/bin/env python3
# coding: utf-8
"""
SmileLoop – Colorize + Animate CLI

Pipeline: B&W photo → colorize (image-to-image) → animate (image-to-video)

Usage:
    source .venv/bin/activate

    # Full pipeline (colorize → video)
    python -m grok_api.colorize_cli photo_bw.jpg --video-prompt "smiles warmly"

    # Colorize only (skip video)
    python -m grok_api.colorize_cli photo_bw.jpg --colorize-only

    # Custom colorize prompt
    python -m grok_api.colorize_cli photo_bw.jpg --colorize-prompt "Add warm sepia tones"

    # 10s video, 720p
    python -m grok_api.colorize_cli photo_bw.jpg --video-prompt "laughs gently" -d 10 -r 720p

Environment:
    KIE_API_KEY  – required
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Load .env if present
_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def main():
    parser = argparse.ArgumentParser(
        description="SmileLoop – Colorize + Animate Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", help="Path to the source B&W image (JPEG or PNG)")
    parser.add_argument(
        "--colorize-prompt",
        default=None,
        help="Custom prompt for colorization (has a good default)",
    )
    parser.add_argument(
        "--video-prompt", "-vp",
        default="smiles warmly and naturally",
        help="Prompt for video animation (default: 'smiles warmly and naturally')",
    )
    parser.add_argument(
        "--colorize-only",
        action="store_true",
        help="Only colorize — skip the video step",
    )
    parser.add_argument(
        "-d", "--duration",
        type=int,
        default=6,
        help="Video duration in seconds (6 or 10, default: 6)",
    )
    parser.add_argument(
        "-r", "--resolution",
        choices=["480p", "720p"],
        default="480p",
        help="Video resolution (default: 480p)",
    )
    parser.add_argument(
        "-m", "--mode",
        choices=["fun", "normal", "spicy"],
        default="normal",
        help="Generation mode (default: normal)",
    )
    parser.add_argument(
        "--image-index",
        type=int,
        default=0,
        choices=[0, 1],
        help="Which colorized image to use (API returns 2, default: 0)",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output path for video (default: <input>_colorized.mp4). "
             "Colorized image is always saved alongside.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="KIE API key (default: from KIE_API_KEY env var)",
    )

    args = parser.parse_args()

    # Validate input image
    image_path = Path(args.image)
    if not image_path.exists():
        print(f"Error: Image not found: {image_path}")
        sys.exit(1)

    image_bytes = image_path.read_bytes()
    if not image_bytes:
        print("Error: Image file is empty.")
        sys.exit(1)

    size_mb = len(image_bytes) / (1024 * 1024)

    # Determine output paths
    stem = image_path.stem
    parent = Path(args.output).parent if args.output else image_path.parent

    if args.output:
        video_out = Path(args.output)
        color_out = video_out.with_suffix(".jpg").with_stem(video_out.stem + "_color")
    else:
        color_out = parent / f"{stem}_colorized.jpg"
        video_out = parent / f"{stem}_colorized.mp4"

    # Print banner
    print()
    print("SmileLoop – Colorize + Animate Pipeline")
    print("────────────────────────────────────────")
    print(f"  Source     : {image_path} ({size_mb:.1f} MB)")
    print(f"  Mode       : {'colorize only' if args.colorize_only else 'colorize → video'}")
    if not args.colorize_only:
        print(f"  Video Prompt: {args.video_prompt}")
        print(f"  Duration   : {args.duration}s")
        print(f"  Resolution : {args.resolution}")
    print(f"  Output img : {color_out}")
    if not args.colorize_only:
        print(f"  Output vid : {video_out}")
    print("────────────────────────────────────────")

    from grok_api.colorize_client import (
        ColorizeError,
        colorize_and_animate,
        colorize_image,
        DEFAULT_COLORIZE_PROMPT,
    )

    api_key = args.api_key or os.environ.get("KIE_API_KEY", "")
    colorize_prompt = args.colorize_prompt or DEFAULT_COLORIZE_PROMPT

    t_start = time.time()

    try:
        if args.colorize_only:
            # Step 1 only
            color_bytes, result_urls = colorize_image(
                image_bytes,
                prompt=colorize_prompt,
                api_key=api_key,
                image_index=args.image_index,
            )
            color_out.parent.mkdir(parents=True, exist_ok=True)
            color_out.write_bytes(color_bytes)

            # Also save the second result if available
            if len(result_urls) > 1:
                alt_path = color_out.with_stem(color_out.stem + "_alt")
                import httpx
                alt_bytes = httpx.get(result_urls[1 - args.image_index], timeout=60, follow_redirects=True).content
                alt_path.write_bytes(alt_bytes)
                print(f"  Alt image  : {alt_path} ({len(alt_bytes):,} bytes)")

            elapsed = time.time() - t_start
            print(f"\n Done! ({elapsed:.1f}s)")
            print(f"  Saved      : {color_out} ({len(color_bytes) / (1024*1024):.2f} MB)")

        else:
            # Full pipeline
            color_bytes, video_bytes = colorize_and_animate(
                image_bytes,
                colorize_prompt=colorize_prompt,
                video_prompt=args.video_prompt,
                duration=args.duration,
                resolution=args.resolution,
                mode=args.mode,
                api_key=api_key,
                image_index=args.image_index,
            )

            # Save outputs
            color_out.parent.mkdir(parents=True, exist_ok=True)
            video_out.parent.mkdir(parents=True, exist_ok=True)
            color_out.write_bytes(color_bytes)
            video_out.write_bytes(video_bytes)

            elapsed = time.time() - t_start
            print(f"\n Done! ({elapsed:.1f}s)")
            print(f"  Color img  : {color_out} ({len(color_bytes) / (1024*1024):.2f} MB)")
            print(f"  Video      : {video_out} ({len(video_bytes) / (1024*1024):.2f} MB)")

    except ColorizeError as e:
        print(f"\n FAILED\n\n  Error: {e}\n")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n  Cancelled by user.")
        sys.exit(130)

    print("\n  Success!")


if __name__ == "__main__":
    main()
