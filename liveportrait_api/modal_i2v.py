# coding: utf-8
"""
SmileLoop – Modal serverless GPU inference for AnimateDiff (Image-to-Video).

Deploy:
    modal deploy liveportrait_api/modal_i2v.py

Test standalone:
    modal run liveportrait_api/modal_i2v.py

Architecture:
    FastAPI (any host) → modal_i2v_client.py → AnimateDiffModel.run (Modal GPU class) → MP4 bytes

Model stack:
  - Base: Stable Diffusion 1.5 (Realistic Vision v5.1)
  - Motion: guoyww/animatediff-motion-adapter-v1-5-3
  - Pipeline: AnimateDiffImg2VideoPipeline (diffusers)
  - Takes an image + text prompt → generates a short animated video
"""

import modal

# ---------------------------------------------------------------------------
# Modal Image – installs everything at build time so cold starts are fast
# ---------------------------------------------------------------------------
i2v_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("ffmpeg", "libgl1-mesa-glx", "libglib2.0-0")
    .pip_install(
        "torch==2.1.2",
        "torchvision==0.16.2",
    )
    .pip_install(
        "diffusers==0.30.3",
        "transformers==4.44.2",
        "accelerate>=0.24.0,<1.0",
        "safetensors>=0.4.0",
        "huggingface-hub>=0.23.2,<1.0",
        "Pillow>=10.0.0",
        "numpy>=1.23.0,<1.27.0",
        "imageio>=2.31.0",
        "imageio-ffmpeg>=0.4.9",
        "opencv-python-headless>=4.8.0",
        "peft>=0.6.0",
    )
    .run_commands(
        "python -c 'import diffusers, transformers; print(f\"diffusers={diffusers.__version__} transformers={transformers.__version__}\")'",
    )
    .run_commands(
        # Pre-download AnimateDiff motion adapter
        'python -c "'
        "from huggingface_hub import snapshot_download; "
        "snapshot_download("
        "    repo_id='guoyww/animatediff-motion-adapter-v1-5-3',"
        "    local_dir='/opt/animatediff-motion-adapter'"
        ")"
        '"',
        # Pre-download a good realistic SD 1.5 base model
        'python -c "'
        "from huggingface_hub import snapshot_download; "
        "snapshot_download("
        "    repo_id='SG161222/Realistic_Vision_V5.1_noVAE',"
        "    local_dir='/opt/realistic-vision-v5',"
        "    ignore_patterns=['*.ckpt', '*.pth']"
        ")"
        '"',
        # Pre-download a good VAE for quality
        'python -c "'
        "from huggingface_hub import snapshot_download; "
        "snapshot_download("
        "    repo_id='stabilityai/sd-vae-ft-mse',"
        "    local_dir='/opt/sd-vae-ft-mse'"
        ")"
        '"',
    )
)

# ---------------------------------------------------------------------------
# Modal App
# ---------------------------------------------------------------------------
app = modal.App("smileloop-i2v", image=i2v_image)

MOTION_ADAPTER_DIR = "/opt/animatediff-motion-adapter"
BASE_MODEL_DIR = "/opt/realistic-vision-v5"
VAE_DIR = "/opt/sd-vae-ft-mse"


# ---------------------------------------------------------------------------
# Class-based singleton — pipeline loads ONCE per container lifecycle.
# ---------------------------------------------------------------------------
@app.cls(gpu="A10G", timeout=300)
class AnimateDiffModel:

    @modal.enter()
    def load_pipeline(self):
        """
        Load AnimateDiff pipeline into GPU memory once.

        Uses AnimateDiffImg2VideoPipeline from diffusers:
          - MotionAdapter provides temporal consistency between frames
          - Realistic Vision v5.1 base for high-quality realistic output
          - SD-VAE-FT-MSE for sharper decode
        """
        import torch
        from diffusers import (
            AnimateDiffImg2VideoPipeline,
            AutoencoderKL,
            DDIMScheduler,
            MotionAdapter,
        )

        print("[AnimateDiff] Loading motion adapter...")
        adapter = MotionAdapter.from_pretrained(
            MOTION_ADAPTER_DIR,
            torch_dtype=torch.float16,
        )

        print("[AnimateDiff] Loading VAE...")
        vae = AutoencoderKL.from_pretrained(
            VAE_DIR,
            torch_dtype=torch.float16,
        )

        print("[AnimateDiff] Loading pipeline (Realistic Vision v5.1 + AnimateDiff)...")
        self.pipe = AnimateDiffImg2VideoPipeline.from_pretrained(
            BASE_MODEL_DIR,
            motion_adapter=adapter,
            vae=vae,
            torch_dtype=torch.float16,
        )

        # DDIM scheduler — best temporal consistency for AnimateDiff
        self.pipe.scheduler = DDIMScheduler.from_pretrained(
            BASE_MODEL_DIR,
            subfolder="scheduler",
            clip_sample=False,
            timestep_spacing="linspace",
            beta_schedule="linear",
            steps_offset=1,
        )

        self.pipe.to("cuda")

        # Memory optimisations
        self.pipe.enable_vae_slicing()

        print("[AnimateDiff] Pipeline ready ✓")

    @modal.method()
    def run(
        self,
        image_bytes: bytes,
        prompt: str = "",
        negative_prompt: str = (
            "ghosting, double exposure, blurry, distorted, disfigured, "
            "ugly, low resolution, bad anatomy, bad hands, watermark, text, "
            "worst quality, low quality, jpeg artifacts"
        ),
        seed: int = 8888,
        num_frames: int = 16,
        num_inference_steps: int = 25,
        guidance_scale: float = 7.5,
        strength: float = 0.7,
        fps: int = 8,
    ) -> bytes:
        """
        Run AnimateDiff image-to-video inference. Returns raw MP4 bytes.

        Args:
            image_bytes:          Raw bytes of the source image (JPEG/PNG).
            prompt:               Text prompt to guide the animation.
            negative_prompt:      Negative prompt to avoid artefacts.
            seed:                 Random seed for reproducibility.
            num_frames:           Number of frames to generate (default 16).
            num_inference_steps:  Diffusion steps (default 25).
            guidance_scale:       CFG scale (default 7.5).
            strength:             How much to transform the image (0=identity, 1=full denoise).
                                  0.7 = preserves image content while adding motion.
            fps:                  Output video FPS (default 8).

        Returns:
            Raw bytes of the output MP4.
        """
        import io
        import numpy as np
        import torch
        from PIL import Image

        # ---- Load and prepare image → 512×512 (SD 1.5 native) ----
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = _prepare_image(img, target_size=512)

        # ---- Run inference ----
        generator = torch.Generator(device="cuda").manual_seed(seed)
        auto_prompt = prompt.strip() if prompt.strip() else "high quality, realistic, smooth natural motion"

        print(f'[AnimateDiff] prompt="{auto_prompt[:80]}" seed={seed} '
              f"frames={num_frames} steps={num_inference_steps} "
              f"cfg={guidance_scale} strength={strength}")

        output = self.pipe(
            prompt=auto_prompt,
            image=img,
            num_frames=num_frames,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            negative_prompt=negative_prompt,
            strength=strength,
            generator=generator,
        )
        frames = output.frames[0]  # list of PIL Images

        # ---- Diagnostic ----
        arr0 = np.array(frames[0]).astype(float)
        arrN = np.array(frames[-1]).astype(float)
        diff = float(np.abs(arr0 - arrN).mean())
        print(f"[AnimateDiff] pixel diff frame0↔frameN = {diff:.2f} (>5 = good motion)")
        print(f"[AnimateDiff] Generated {len(frames)} frames at {frames[0].size}")

        # ---- Encode to MP4 ----
        return _encode_mp4(frames, fps)


# ---------------------------------------------------------------------------
# Helper: prepare image (face-aware crop to square for SD 1.5)
# ---------------------------------------------------------------------------
def _prepare_image(img, target_size: int = 512):
    """Crop and resize to target_size × target_size (SD 1.5 native)."""
    from PIL import Image

    src_w, src_h = img.size

    # Face-aware square crop
    face_cx, face_cy = _detect_face_center(img)

    side = min(src_w, src_h)
    if face_cx is not None:
        left = max(0, face_cx - side // 2)
        left = min(left, src_w - side)
        top = max(0, face_cy - int(side * 0.40))
        top = min(top, src_h - side)
        img = img.crop((left, top, left + side, top + side))
        print(f"[AnimateDiff] Face-aware crop around ({face_cx}, {face_cy})")
    else:
        if src_w > src_h:
            left = (src_w - src_h) // 2
            img = img.crop((left, 0, left + src_h, src_h))
        else:
            top = (src_h - src_w) // 4
            top = max(0, min(top, src_h - src_w))
            img = img.crop((0, top, src_w, top + src_w))
        print("[AnimateDiff] Center-crop to square")

    return img.resize((target_size, target_size), Image.LANCZOS)


def _detect_face_center(img):
    """Detect the largest face using OpenCV Haar cascade."""
    import cv2
    import numpy as np

    gray = np.array(img.convert("L"))
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))

    if len(faces) == 0:
        return None, None

    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    return x + w // 2, y + h // 2


# ---------------------------------------------------------------------------
# Helper: high-quality ffmpeg H.264 encode
# ---------------------------------------------------------------------------
def _encode_mp4(frames: list, fps: int) -> bytes:
    """Encode PIL Image frames to MP4 using ffmpeg H.264."""
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        for i, frame in enumerate(frames):
            frame.save(tmpdir / f"frame_{i:04d}.png")

        output_path = tmpdir / "output.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(tmpdir / "frame_%04d.png"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "medium",
            "-crf", "18",
            "-movflags", "+faststart",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[AnimateDiff] ffmpeg stderr: {result.stderr}")
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")

        return output_path.read_bytes()


# ---------------------------------------------------------------------------
# Standalone function wrapper (used by modal_i2v_client.py)
# ---------------------------------------------------------------------------
@app.function(gpu="A10G", timeout=300)
def run_i2v(
    image_bytes: bytes,
    prompt: str = "",
    negative_prompt: str = (
        "ghosting, double exposure, blurry, distorted, disfigured, "
        "ugly, low resolution, bad anatomy, bad hands, watermark, text, "
        "worst quality, low quality, jpeg artifacts"
    ),
    seed: int = 8888,
    num_frames: int = 16,
    num_inference_steps: int = 25,
    guidance_scale: float = 7.5,
    strength: float = 0.7,
    fps: int = 8,
) -> bytes:
    """Standalone function entrypoint — delegates to AnimateDiffModel."""
    model = AnimateDiffModel()
    return model.run.local(
        image_bytes,
        prompt=prompt,
        negative_prompt=negative_prompt,
        seed=seed,
        num_frames=num_frames,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        strength=strength,
        fps=fps,
    )


# ---------------------------------------------------------------------------
# CLI entry point for testing:  modal run liveportrait_api/modal_i2v.py
# ---------------------------------------------------------------------------
@app.local_entrypoint()
def main():
    """Smoke test — generate video from a test image using AnimateDiff."""
    from pathlib import Path

    test_image_path = Path("public/assets/user_uploaded_images/Olena.jpg")
    if test_image_path.exists():
        image_bytes = test_image_path.read_bytes()
        print(f"Using test image: {test_image_path}")
    else:
        import base64
        tiny_jpeg = base64.b64decode(
            "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoH"
            "BwYIDAoMCwsKCwsNCxAQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQME"
            "BAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQU"
            "FBQUFBQUFBQUFBT/wgARCAAIAAgDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf"
            "/EABQBAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhADEAAAAX8P/8QAFBABAAAAAAAAAA"
            "AAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF/"
            "/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAA"
            "AAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oA"
            "DAMBAAIAAwAAABCf/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPxBf/8QAFBEB"
            "AAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPxBf/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/a"
            "AAgBAQABPxBf/9k="
        )
        image_bytes = tiny_jpeg
        print("Using minimal synthetic test image")

    print("Submitting AnimateDiff job to Modal...")
    try:
        mp4 = run_i2v.remote(
            image_bytes,
            prompt="gentle natural movement, cinematic, high quality",
            seed=8888,
            num_frames=16,
            num_inference_steps=25,
            guidance_scale=7.5,
            strength=0.7,
        )
        out = "modal_i2v_test_output.mp4"
        Path(out).write_bytes(mp4)
        print(f"✓ Saved {len(mp4):,} bytes → {out}")
    except Exception as e:
        print(f"✗ Error: {e}")
        raise
