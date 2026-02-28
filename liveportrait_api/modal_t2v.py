# coding: utf-8
"""
SmileLoop – Modal serverless GPU inference for ModelScope Text-to-Video.

Deploy:
    modal deploy liveportrait_api/modal_t2v.py

Test standalone:
    modal run liveportrait_api/modal_t2v.py

Architecture:
    FastAPI (any host) → modal_t2v_client.py → T2VModel.run (Modal GPU class) → MP4 bytes
"""

import modal

# ---------------------------------------------------------------------------
# Modal Image – installs everything at build time so cold starts are fast
# ---------------------------------------------------------------------------
t2v_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("ffmpeg", "libgl1-mesa-glx", "libglib2.0-0")
    .pip_install(
        # Step 1: Pin core deps that modelscope 1.4.2 is sensitive to
        "numpy==1.23.5",
        "pyarrow==11.0.0",
        "datasets==2.8.0",
    )
    .pip_install(
        # Step 2: modelscope + ML stack with compatible versions
        # transformers must be <4.46 to avoid register_pytree_node issue with torch 2.1
        # open_clip_torch must be <2.27 to avoid torchvision compat issues
        "torch==2.1.2",
        "torchvision==0.16.2",
        "transformers==4.38.2",
        "open_clip_torch==2.24.0",
        "modelscope==1.4.2",
        "pytorch-lightning",
        "huggingface-hub>=0.20.0,<1.0",
        "Pillow>=10.0.0",
        "imageio>=2.31.0",
        "imageio-ffmpeg>=0.4.9",
        "opencv-python-headless>=4.8.0",
        "safetensors>=0.4.0",
        "accelerate>=0.24.0,<1.0",
    )
    .run_commands(
        # Pre-download ModelScope text-to-video weights at build time
        'python -c "'
        "from huggingface_hub import snapshot_download; "
        "snapshot_download("
        "    repo_id='damo-vilab/modelscope-damo-text-to-video-synthesis',"
        "    repo_type='model',"
        "    local_dir='/opt/modelscope-t2v'"
        ")"
        '"',
    )
)

# ---------------------------------------------------------------------------
# Modal App
# ---------------------------------------------------------------------------
app = modal.App("smileloop-t2v", image=t2v_image)

T2V_MODEL_DIR = "/opt/modelscope-t2v"


# ---------------------------------------------------------------------------
# Class-based singleton — pipeline loads ONCE per container lifecycle.
# Without this, every call would reload ~10GB of weights.
# ---------------------------------------------------------------------------
@app.cls(gpu="A10G", timeout=300)
class T2VModel:

    @modal.enter()
    def load_pipeline(self):
        """
        Called once when the container starts. Loads the ModelScope
        text-to-video pipeline into GPU memory.
        """
        from modelscope.pipelines import pipeline

        print("[T2V] Loading ModelScope text-to-video pipeline...")
        self.pipe = pipeline("text-to-video-synthesis", T2V_MODEL_DIR)
        print("[T2V] Pipeline ready ✓")

    @modal.method()
    def run(
        self,
        prompt: str,
        seed: int = -1,
        num_frames: int = 16,
        num_inference_steps: int = 50,
        fps: int = 8,
    ) -> bytes:
        """
        Run ModelScope text-to-video inference. Returns raw MP4 bytes.

        Args:
            prompt:               English text description.
            seed:                 Random seed (-1 = random). >=0 for reproducible.
            num_frames:           Number of frames to generate (default 16).
            num_inference_steps:  Diffusion steps (default 50, higher = better quality).
            fps:                  Output video FPS (default 8).

        Returns:
            Raw bytes of the output MP4.
        """
        import random
        import subprocess
        import tempfile
        from pathlib import Path

        from modelscope.outputs import OutputKeys

        # Build input payload
        test_text = {"text": prompt}
        if seed >= 0:
            test_text["seed"] = seed
        else:
            test_text["seed"] = random.randint(0, 2**32 - 1)
        if num_frames != 16:
            test_text["num_frames"] = num_frames
        if num_inference_steps != 50:
            test_text["num_inference_steps"] = num_inference_steps

        print(f'[T2V] Generating video: "{prompt}" (seed={test_text["seed"]}, '
              f"frames={num_frames}, steps={num_inference_steps})")

        # Run the pipeline
        result = self.pipe(test_text)
        src_path = Path(result[OutputKeys.OUTPUT_VIDEO])

        if not src_path.exists():
            raise RuntimeError("ModelScope produced no output video.")

        # Re-encode with ffmpeg for consistent output (yuv420p, proper fps)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(src_path),
                "-r", str(fps),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                tmp_path,
            ]
            subprocess.run(cmd, capture_output=True, check=True, timeout=60)
            mp4_bytes = Path(tmp_path).read_bytes()
        except subprocess.CalledProcessError:
            # Fallback: return raw output without re-encoding
            mp4_bytes = src_path.read_bytes()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        print(f"[T2V] Done — {len(mp4_bytes):,} bytes")
        return mp4_bytes


# ---------------------------------------------------------------------------
# Standalone function wrapper (used by modal_t2v_client.py via Function.from_name)
# ---------------------------------------------------------------------------
@app.function(gpu="A10G", timeout=300)
def run_t2v(
    prompt: str,
    seed: int = -1,
    num_frames: int = 16,
    num_inference_steps: int = 50,
    fps: int = 8,
) -> bytes:
    """
    Standalone wrapper for Function.from_name() calls.
    Delegates to a fresh pipeline each call (use T2VModel.run for warm containers).
    """
    from modelscope.pipelines import pipeline as ms_pipeline
    from modelscope.outputs import OutputKeys
    import random
    import subprocess
    import tempfile
    from pathlib import Path

    pipe = ms_pipeline("text-to-video-synthesis", T2V_MODEL_DIR)

    test_text = {"text": prompt}
    test_text["seed"] = seed if seed >= 0 else random.randint(0, 2**32 - 1)
    if num_frames != 16:
        test_text["num_frames"] = num_frames
    if num_inference_steps != 50:
        test_text["num_inference_steps"] = num_inference_steps

    result = pipe(test_text)
    src_path = Path(result[OutputKeys.OUTPUT_VIDEO])

    if not src_path.exists():
        raise RuntimeError("ModelScope produced no output video.")

    # Re-encode
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        cmd = [
            "ffmpeg", "-y", "-i", str(src_path),
            "-r", str(fps), "-c:v", "libx264", "-preset", "medium",
            "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            tmp_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True, timeout=60)
        mp4_bytes = Path(tmp_path).read_bytes()
    except subprocess.CalledProcessError:
        mp4_bytes = src_path.read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return mp4_bytes


# ---------------------------------------------------------------------------
# CLI entry point for testing:  modal run liveportrait_api/modal_t2v.py
# ---------------------------------------------------------------------------
@app.local_entrypoint()
def main():
    """Quick smoke test — generate a short video from a text prompt."""
    print("Submitting test job to Modal...")
    try:
        mp4 = run_t2v.remote(
            "A panda eating bamboo on a rock.",
            seed=42,
            num_frames=16,
            num_inference_steps=50,
        )
        print(f"✓ Got {len(mp4):,} bytes of MP4 back.")
        with open("modal_t2v_test_output.mp4", "wb") as f:
            f.write(mp4)
        print("✓ Saved to modal_t2v_test_output.mp4")
    except Exception as e:
        print(f"✗ Error: {e}")
