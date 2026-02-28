#!/usr/bin/env python3
"""
Quick test script for ModelScope Text-to-Video synthesis.

Supports two modes:
  local  - runs inference locally (needs GPU + ~16GB VRAM)
  modal  - runs on Modal serverless GPU (just needs `modal` + `pip install modal`)
  api    - calls the SmileLoop FastAPI /generate-video endpoint

Usage:
    # Modal (recommended — no local GPU needed):
    python test_text_to_video.py --mode modal
    python test_text_to_video.py --mode modal --prompt "A cat playing with a ball"

    # Local GPU:
    python test_text_to_video.py --mode local --prompt "Ocean waves at sunset" --seed 42

    # Via SmileLoop API:
    python test_text_to_video.py --mode api --api-url http://localhost:8000

Requirements:
    modal mode:  pip install modal
    local mode:  pip install -r requirements_t2v.txt  (+ ~16GB GPU VRAM)
    api mode:    pip install requests
"""

import argparse
import pathlib
import sys
import time


def generate_video_modal(
    prompt: str,
    output_dir: pathlib.Path,
    seed: int = -1,
    num_frames: int = 16,
    num_inference_steps: int = 50,
    fps: int = 8,
) -> pathlib.Path:
    """Generate a video using Modal serverless GPU (no local GPU needed)."""
    import modal

    print("[⚙] Connecting to Modal function 'smileloop-t2v' / 'run_t2v' …")
    fn = modal.Function.from_name("smileloop-t2v", "run_t2v")

    print(f'[▶] Generating video: "{prompt}"')
    print(f"    seed={seed}  frames={num_frames}  steps={num_inference_steps}  fps={fps}")

    start = time.time()
    mp4_bytes = fn.remote(
        prompt,
        seed=seed,
        num_frames=num_frames,
        num_inference_steps=num_inference_steps,
        fps=fps,
    )
    elapsed = time.time() - start

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = prompt[:60].replace(" ", "_").replace("/", "-")
    dest = output_dir / f"{safe_name}.mp4"
    counter = 1
    while dest.exists():
        dest = output_dir / f"{safe_name}_{counter}.mp4"
        counter += 1

    dest.write_bytes(mp4_bytes)
    print(f"\n[✓] Video generated in {elapsed:.1f}s ({len(mp4_bytes):,} bytes)")
    print(f"    → {dest}")
    return dest


def generate_video_api(
    prompt: str,
    output_dir: pathlib.Path,
    api_url: str = "http://localhost:8000",
    seed: int = -1,
    num_frames: int = 16,
    num_inference_steps: int = 50,
    fps: int = 8,
) -> pathlib.Path:
    """Generate a video via the SmileLoop FastAPI /generate-video endpoint."""
    import requests

    url = f"{api_url.rstrip('/')}/generate-video"
    print(f"[⚙] Calling {url} …")
    print(f'[▶] Generating video: "{prompt}"')
    print(f"    seed={seed}  frames={num_frames}  steps={num_inference_steps}  fps={fps}")

    start = time.time()
    resp = requests.post(
        url,
        data={
            "prompt": prompt,
            "seed": seed,
            "num_frames": num_frames,
            "num_inference_steps": num_inference_steps,
            "fps": fps,
        },
        timeout=300,
    )
    elapsed = time.time() - start

    if resp.status_code != 200:
        raise RuntimeError(f"API returned {resp.status_code}: {resp.text[:500]}")

    mp4_bytes = resp.content
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = prompt[:60].replace(" ", "_").replace("/", "-")
    dest = output_dir / f"{safe_name}.mp4"
    counter = 1
    while dest.exists():
        dest = output_dir / f"{safe_name}_{counter}.mp4"
        counter += 1

    dest.write_bytes(mp4_bytes)
    print(f"\n[✓] Video generated in {elapsed:.1f}s ({len(mp4_bytes):,} bytes)")
    print(f"    → {dest}")
    return dest


def download_model(model_dir: pathlib.Path) -> None:
    """Download model weights from HuggingFace if not already present."""
    from huggingface_hub import snapshot_download

    if (model_dir / "configuration.json").exists():
        print(f"[✓] Model weights already present at {model_dir}")
        return

    print("[↓] Downloading ModelScope text-to-video model weights …")
    print("    (this can take a while the first time — ~10 GB)")
    snapshot_download(
        "damo-vilab/modelscope-damo-text-to-video-synthesis",
        repo_type="model",
        local_dir=str(model_dir),
    )
    print(f"[✓] Weights saved to {model_dir}")


def generate_video(
    prompt: str,
    model_dir: pathlib.Path,
    output_dir: pathlib.Path,
    seed: int = -1,
    num_frames: int = 16,
    num_inference_steps: int = 50,
) -> pathlib.Path:
    """Generate a video from a text prompt and return the output path."""
    from modelscope.pipelines import pipeline
    from modelscope.outputs import OutputKeys

    print(f"\n[⚙] Initialising pipeline from {model_dir} …")
    pipe = pipeline("text-to-video-synthesis", model_dir.as_posix())

    # Build input payload
    test_text = {"text": prompt}
    if seed >= 0:
        test_text["seed"] = seed
    if num_frames != 16:
        test_text["num_frames"] = num_frames
    if num_inference_steps != 50:
        test_text["num_inference_steps"] = num_inference_steps

    print(f'[▶] Generating video for prompt: "{prompt}"')
    print(f"    seed={seed}  frames={num_frames}  steps={num_inference_steps}")

    start = time.time()
    result = pipe(test_text)
    elapsed = time.time() - start

    src_path = pathlib.Path(result[OutputKeys.OUTPUT_VIDEO])
    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy to our output folder with a readable name
    safe_name = prompt[:60].replace(" ", "_").replace("/", "-")
    dest = output_dir / f"{safe_name}.mp4"
    counter = 1
    while dest.exists():
        dest = output_dir / f"{safe_name}_{counter}.mp4"
        counter += 1

    import shutil
    shutil.copy2(src_path, dest)

    print(f"\n[✓] Video generated in {elapsed:.1f}s")
    print(f"    → {dest}")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ModelScope Text-to-Video — quick test"
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="modal",
        choices=["local", "modal", "api"],
        help="Inference mode: modal (serverless GPU), local (needs GPU), api (SmileLoop endpoint)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="A panda eating bamboo on a rock.",
        help="English text description for the video (default: panda eating bamboo)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=-1,
        help="Random seed (-1 = random each run, >=0 = reproducible)",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=16,
        help="Number of frames to generate (default: 16)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=50,
        help="Number of diffusion inference steps (default: 50, higher = better quality)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=8,
        help="Output video FPS (default: 8)",
    )
    parser.add_argument(
        "--model-dir",
        type=str,
        default=None,
        help="[local mode] Path to model weights (default: ./weights)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for generated videos (default: ./outputs)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default="http://localhost:8000",
        help="[api mode] SmileLoop API base URL (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    script_dir = pathlib.Path(__file__).resolve().parent
    output_dir = pathlib.Path(args.output_dir) if args.output_dir else script_dir / "outputs"

    print("=" * 60)
    print(f"  ModelScope Text-to-Video — Quick Test  (mode: {args.mode})")
    print("=" * 60)

    if args.mode == "modal":
        output_path = generate_video_modal(
            prompt=args.prompt,
            output_dir=output_dir,
            seed=args.seed,
            num_frames=args.frames,
            num_inference_steps=args.steps,
            fps=args.fps,
        )

    elif args.mode == "api":
        output_path = generate_video_api(
            prompt=args.prompt,
            output_dir=output_dir,
            api_url=args.api_url,
            seed=args.seed,
            num_frames=args.frames,
            num_inference_steps=args.steps,
            fps=args.fps,
        )

    else:  # local
        model_dir = pathlib.Path(args.model_dir) if args.model_dir else script_dir / "weights"
        download_model(model_dir)
        output_path = generate_video(
            prompt=args.prompt,
            model_dir=model_dir,
            output_dir=output_dir,
            seed=args.seed,
            num_frames=args.frames,
            num_inference_steps=args.steps,
        )

    print(f"\nDone! Open the video with:  open {output_path}")


if __name__ == "__main__":
    main()
