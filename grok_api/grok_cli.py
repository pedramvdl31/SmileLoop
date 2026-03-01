#!/usr/bin/env python3
# coding: utf-8
"""
SmileLoop – Grok Video CLI

Test the Grok video generation from the command line.

Usage:
    # Activate venv first
    source .venv/bin/activate

    # Generate via xAI SDK (default)
    python -m grok_api.grok_cli photo.jpg --prompt "smiles warmly"

    # Generate via KIE API
    python -m grok_api.grok_cli photo.jpg --prompt "smiles warmly" --provider kie

    # Custom duration, resolution, mode
    python -m grok_api.grok_cli photo.jpg --prompt "waves hello" -d 6 -r 720p --mode normal

    # Specify output path
    python -m grok_api.grok_cli photo.jpg --prompt "laughs gently" -o result.mp4

Environment:
    XAI_API_KEY  – required for --provider xai (default)
    KIE_API_KEY  – required for --provider kie
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
        description="SmileLoop – Grok Video Generation CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "image",
        help="Path to the source portrait image (JPEG or PNG)",
    )
    parser.add_argument(
        "-p", "--prompt",
        required=True,
        help="Text prompt describing the desired video (e.g. 'smiles warmly')",
    )
    parser.add_argument(
        "--provider",
        default="xai",
        choices=["xai", "kie"],
        help="API provider: 'xai' = direct xAI SDK, 'kie' = KIE proxy API (default: xai)",
    )
    parser.add_argument(
        "-d", "--duration",
        type=int,
        default=6,
        help="Video duration in seconds (default: 6). KIE supports 6 or 10 only.",
    )
    parser.add_argument(
        "-r", "--resolution",
        default="480p",
        choices=["480p", "720p"],
        help="Video resolution (default: 480p)",
    )
    parser.add_argument(
        "-m", "--mode",
        default="normal",
        choices=["fun", "normal", "spicy"],
        help="Generation mode (default: normal). Only used with KIE provider.",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output file path (default: <input>_grok.mp4)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key (default: from XAI_API_KEY or KIE_API_KEY env var)",
    )

    args = parser.parse_args()

    # Validate input
    src = Path(args.image)
    if not src.exists():
        print(f"Error: File not found: {src}", file=sys.stderr)
        sys.exit(1)

    if src.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        print(f"Error: Unsupported format '{src.suffix}'. Use JPG or PNG.", file=sys.stderr)
        sys.exit(1)

    # Build output path
    out_path = Path(args.output) if args.output else src.parent / f"{src.stem}_grok.mp4"

    # Read image
    image_bytes = src.read_bytes()
    size_mb = len(image_bytes) / (1024 * 1024)

    provider_label = "xAI SDK" if args.provider == "xai" else "KIE API"
    print(f"SmileLoop – Grok Video Generation")
    print(f"{'─' * 40}")
    print(f"  Provider   : {provider_label}")
    print(f"  Source     : {src} ({size_mb:.1f} MB)")
    print(f"  Prompt     : {args.prompt}")
    print(f"  Duration   : {args.duration}s")
    print(f"  Resolution : {args.resolution}")
    if args.provider == "kie":
        print(f"  Mode       : {args.mode}")
    print(f"  Output     : {out_path}")
    print(f"{'─' * 40}")
    print(f"  Generating video...", end="", flush=True)

    t0 = time.time()

    if args.provider == "kie":
        from grok_api.kie_client import KieError, kie_generate_video
        try:
            result_bytes = kie_generate_video(
                image_bytes=image_bytes,
                prompt=args.prompt,
                duration=args.duration,
                resolution=args.resolution,
                mode=args.mode,
                api_key=args.api_key,
                source="cli",
            )
        except KieError as e:
            print(f" FAILED")
            print(f"\n  Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        from grok_api.grok_client import GrokError, grok_generate_video
        try:
            result_bytes = grok_generate_video(
                image_bytes=image_bytes,
                prompt=args.prompt,
                duration=args.duration,
                resolution=args.resolution,
                api_key=args.api_key,
                source="cli",
            )
        except GrokError as e:
            print(f" FAILED")
            print(f"\n  Error: {e}", file=sys.stderr)
            sys.exit(1)

    elapsed = time.time() - t0
    print(f" Done! ({elapsed:.1f}s)")

    # Save result
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(result_bytes)
    result_mb = len(result_bytes) / (1024 * 1024)
    print(f"  Saved      : {out_path} ({result_mb:.2f} MB)")
    print(f"\n  Success!")


if __name__ == "__main__":
    main()
