# coding: utf-8
"""
SmileLoop – Modal serverless GPU inference for LivePortrait.

Deploy:
    modal deploy liveportrait_api/modal_liveportrait.py

Test standalone:
    modal run liveportrait_api/modal_liveportrait.py

Architecture:
    FastAPI (any host) → modal_client.py → this Modal function (GPU) → MP4 bytes
"""

import modal

# ---------------------------------------------------------------------------
# Modal Image – installs everything at build time so cold starts are fast
# ---------------------------------------------------------------------------
liveportrait_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git", "ffmpeg", "libgl1-mesa-glx", "libglib2.0-0")
    .pip_install(
        "torch>=2.0.0",
        "torchvision>=0.15.0",
        "opencv-python-headless>=4.8.0",
        "pillow>=10.0.0",
        "numpy>=1.24.0",
        "onnxruntime-gpu>=1.16.0",
        "onnx>=1.14.0",
        "imageio>=2.31.0",
        "imageio-ffmpeg>=0.4.9",
        "scikit-image>=0.21.0",
        "scipy>=1.11.0",
        "tqdm>=4.65.0",
        "pyyaml>=6.0",
        "safetensors>=0.4.0",
        "huggingface-hub>=0.20.0",
        "lmdb>=1.4.0",
        "albumentations>=1.3.0",
        "rich>=13.0.0",
        "ffmpeg-python>=0.2.0",
        "tyro>=0.7.0",
        "requests>=2.28.0",
        "pykalman>=0.9.7",
        "transformers>=4.38.0",
    )
    .run_commands(
        # Clone LivePortrait
        "git clone https://github.com/KlingAIResearch/LivePortrait.git /opt/LivePortrait",
        # Download pretrained weights
        'python -c "'
        "from huggingface_hub import snapshot_download; "
        "snapshot_download("
        "    repo_id='KwaiVGI/LivePortrait',"
        "    local_dir='/opt/LivePortrait/pretrained_weights/liveportrait'"
        ")"
        '"',
        # Fix nested directory structure from HuggingFace download
        "cd /opt/LivePortrait/pretrained_weights/liveportrait && "
        "cp -r liveportrait/base_models . 2>/dev/null || true && "
        "cp -r liveportrait/retargeting_models . 2>/dev/null || true && "
        "cp liveportrait/landmark.onnx . 2>/dev/null || true",
    )
)

# ---------------------------------------------------------------------------
# Modal App
# ---------------------------------------------------------------------------
app = modal.App("smileloop-liveportrait", image=liveportrait_image)

# ---------------------------------------------------------------------------
# Volume for preset driving videos (uploaded once, shared across calls)
# ---------------------------------------------------------------------------
presets_volume = modal.Volume.from_name("smileloop-presets", create_if_missing=True)

LIVEPORTRAIT_ROOT = "/opt/LivePortrait"
PRESETS_MOUNT = "/data/presets"


@app.function(
    gpu="T4",
    timeout=300,
    volumes={PRESETS_MOUNT: presets_volume},
    allow_concurrent_inputs=1,
)
def run_liveportrait(image_bytes: bytes, preset: str, driving_video_bytes: bytes | None = None) -> bytes:
    """
    Run LivePortrait inference on a GPU.

    Args:
        image_bytes:         Raw bytes of the source portrait (JPEG or PNG).
        preset:              Name of the driving-motion preset (e.g. "d6_1s").
        driving_video_bytes: Optional raw bytes of the driving video.
                             If provided, saved to the presets volume for reuse.
                             If None, the preset must already exist in the volume.

    Returns:
        Raw bytes of the output MP4.
    """
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    # --- Resolve driving video ---
    driving_path = Path(PRESETS_MOUNT) / f"{preset}.mp4"

    if driving_video_bytes:
        # Upload driving video to persistent volume
        driving_path.write_bytes(driving_video_bytes)
        presets_volume.commit()

    if not driving_path.exists():
        raise FileNotFoundError(
            f"Driving video for preset '{preset}' not found. "
            f"Upload it by passing driving_video_bytes on the first call."
        )

    # --- Temp workspace ---
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        source_path = tmp / "source.jpg"
        output_dir = tmp / "output"
        output_dir.mkdir()

        source_path.write_bytes(image_bytes)

        # --- Run LivePortrait inference ---
        cmd = [
            sys.executable,
            f"{LIVEPORTRAIT_ROOT}/inference.py",
            "-s", str(source_path),
            "-d", str(driving_path),
            "-o", str(output_dir),
            "--flag_crop_driving_video",
        ]

        result = subprocess.run(
            cmd,
            cwd=LIVEPORTRAIT_ROOT,
            capture_output=True,
            text=True,
            timeout=240,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"LivePortrait inference failed (exit {result.returncode}):\n"
                f"{result.stderr[-2000:]}"
            )

        # --- Find output MP4 ---
        mp4s = sorted(output_dir.glob("*.mp4"))
        non_concat = [f for f in mp4s if "_concat" not in f.stem]
        result_path = non_concat[0] if non_concat else (mp4s[0] if mp4s else None)

        if result_path is None or not result_path.exists():
            raise RuntimeError("LivePortrait produced no output MP4.")

        return result_path.read_bytes()


# ---------------------------------------------------------------------------
# CLI entry point for testing:  modal run modal_liveportrait.py
# ---------------------------------------------------------------------------
@app.local_entrypoint()
def main():
    """Quick smoke test – animate a tiny white image."""
    from PIL import Image
    import io

    # Create a small test image
    img = Image.new("RGB", (256, 256), color=(200, 180, 160))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    test_bytes = buf.getvalue()

    print("Submitting test job to Modal...")
    try:
        mp4 = run_liveportrait.remote(test_bytes, "d6_1s")
        print(f"✓ Got {len(mp4):,} bytes of MP4 back.")
        with open("modal_test_output.mp4", "wb") as f:
            f.write(mp4)
        print("✓ Saved to modal_test_output.mp4")
    except Exception as e:
        print(f"✗ Error: {e}")
