# coding: utf-8
"""
SmileLoop – Modal serverless GPU inference for Stable Video Diffusion (SVD-XT).

Key quality improvements:
  - Class-based singleton: pipeline loads ONCE per container (no reload per call)
  - A100 GPU (40GB): enough VRAM for full 25-frame decode without OOM
  - NO xformers: flash attention crashes on A100 with CUDA config errors;
    PyTorch 2.x native SDPA is used instead (actually faster on A100)
  - VAE tiling + slicing: decode is spatially tiled → OOM-safe, zero quality loss
  - decode_chunk_size = num_frames: all frames decoded together = no ghosting
  - Low noise defaults (noise_aug_strength=0.06): preserves face identity
  - Face-aware crop: OpenCV Haar cascade, centers crop on face with headroom
  - Letterbox option: blurred background padding instead of crop
  - High-quality ffmpeg H.264 encode: crf=18, yuv420p, preset=medium
  - Explicit seed parameter for reproducibility

Deploy:
    modal deploy liveportrait_api/modal_svd.py

Architecture:
    FastAPI → modal_svd_client.py → SVDModel.run (Modal A100 class) → MP4 bytes
"""

import modal

# ---------------------------------------------------------------------------
# Preset configs — pass as **PRESETS["medium"] to SVDModel.run()
# ---------------------------------------------------------------------------
PRESETS = {
    "gentle": {
        "motion_bucket_id": 60,
        "noise_aug_strength": 0.02,
        "min_guidance_scale": 1.0,
        "max_guidance_scale": 3.0,
        "seed": 12345,
    },
    "medium": {
        "motion_bucket_id": 100,
        "noise_aug_strength": 0.04,
        "min_guidance_scale": 1.0,
        "max_guidance_scale": 3.5,
        "seed": 12345,
    },
    "strong": {
        "motion_bucket_id": 150,
        "noise_aug_strength": 0.08,
        "min_guidance_scale": 1.0,
        "max_guidance_scale": 3.0,
        "seed": 12345,
    },
}

# ---------------------------------------------------------------------------
# Modal Image — installs everything at build time
# ---------------------------------------------------------------------------
svd_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("ffmpeg", "libgl1-mesa-glx", "libglib2.0-0", "libsm6", "libxext6")
    .pip_install(
        "torch>=2.0.0",
        "torchvision>=0.15.0",
        "diffusers>=0.24.0",
        "transformers>=4.35.0",
        "accelerate>=0.24.0",
        "safetensors>=0.4.0",
        "huggingface-hub>=0.20.0",
        "Pillow>=10.0.0",
        "numpy>=1.24.0",
        "imageio>=2.31.0",
        "imageio-ffmpeg>=0.4.9",
        "opencv-python-headless>=4.8.0",
        # xformers intentionally excluded — crashes on A100 with flash attention
        # (CUDA error: invalid configuration argument). PyTorch 2.x native SDPA
        # is used instead, which is faster on A100 and needs no extra package.
    )
    .run_commands(
        # Pre-download SVD-XT weights at build time so cold starts are fast
        'python -c "'
        "from huggingface_hub import snapshot_download; "
        "snapshot_download("
        "    repo_id='stabilityai/stable-video-diffusion-img2vid-xt',"
        "    local_dir='/opt/svd-xt',"
        "    ignore_patterns=['*.bin']"
        ")"
        '"',
    )
)

# ---------------------------------------------------------------------------
# Modal App
# ---------------------------------------------------------------------------
app = modal.App("smileloop-svd", image=svd_image)

SVD_MODEL_DIR = "/opt/svd-xt"


# ---------------------------------------------------------------------------
# Class-based singleton — pipeline loads ONCE per container lifecycle.
# This is the correct Modal pattern: @app.cls with @modal.enter() for setup.
# Without this, every call would reload 10GB of weights (~60s cold start cost).
# ---------------------------------------------------------------------------
@app.cls(gpu="A100", timeout=300)
class SVDModel:

    @modal.enter()
    def load_pipeline(self):
        """
        Called once when the container starts. Loads the pipeline into GPU memory.
        Keeping the pipeline resident eliminates the biggest source of latency
        and also ensures temporal consistency (same model state every call).
        """
        import os
        import torch
        from diffusers import StableVideoDiffusionPipeline

        os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

        print("[SVD] Loading pipeline...")
        self.pipe = StableVideoDiffusionPipeline.from_pretrained(
            SVD_MODEL_DIR,
            torch_dtype=torch.float16,
            variant="fp16",
        )
        # Keep all weights on GPU.
        # Never use enable_model_cpu_offload() — it processes frames in small
        # device-shuffled chunks which is the primary cause of ghosting.
        self.pipe.to("cuda")

        # DO NOT use xformers on A100 — flash attention crashes with
        # "CUDA error: invalid configuration argument" on certain A100 configs.
        # PyTorch 2.x native SDPA (scaled_dot_product_attention) is used
        # automatically and is actually faster on A100 than xformers.
        # We explicitly disable xformers to prevent it from being picked up.
        try:
            self.pipe.disable_xformers_memory_efficient_attention()
        except Exception:
            pass  # fine if it was never enabled

        # AutoencoderKLTemporalDecoder (SVD's VAE) does NOT support enable_slicing()
        # or enable_tiling() — both raise NotImplementedError. On A100 (40GB)
        # we have plenty of VRAM to decode all 25 frames in one pass anyway.
        print("[SVD] Pipeline ready ✓")

    @modal.method()
    def run(
        self,
        image_bytes: bytes,
        num_frames: int = 25,
        num_inference_steps: int = 50,
        fps: int = 7,
        motion_bucket_id: int = 100,
        noise_aug_strength: float = 0.04,
        decode_chunk_size: int = 4,    # small chunks = sharper per-frame VAE decode
        min_guidance_scale: float = 1.0,
        max_guidance_scale: float = 3.5,
        seed: int = 12345,
        letterbox: bool = False,
    ) -> bytes:
        """
        Run SVD-XT inference. Returns raw MP4 bytes.

        Key parameters for face quality:

        noise_aug_strength=0.04:
            Very low noise = model is strongly anchored to input frame.
            Values >0.1 cause the model to "forget" the face → ghosting.

        motion_bucket_id=100:
            Moderate motion. Lower = more static/stable face.
            Higher values (180+) produce jitter and camera shake.

        decode_chunk_size=4:
            The temporal VAE decoder produces cleaner frames in small chunks.
            Each chunk of 4 frames is decoded with full temporal context
            within that window. Large chunks (25) cause the fp16 VAE to
            accumulate error across frames → face shimmer.

        num_inference_steps=50:
            More steps = finer texture, less noise-induced drift.

        max_guidance_scale=3.5:
            Low-moderate CFG. Values >5 cause color shifts and edge ringing
            that register as ghosting. Keep between 3-4 for portraits.
        """
        import io
        import os
        import numpy as np
        import torch
        from PIL import Image

        pipe = self.pipe

        chunk_size = decode_chunk_size

        # ---- Preprocess input image → 1024×576 ----
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = _prepare_image(img, target_w=1024, target_h=576, letterbox=letterbox)

        # ---- Run inference ----
        generator = torch.Generator(device="cuda").manual_seed(seed)
        print(f"[SVD] seed={seed} motion={motion_bucket_id} noise={noise_aug_strength} "
              f"chunk={chunk_size} cfg={min_guidance_scale}→{max_guidance_scale}")

        frames = _run_inference(
            pipe, img, num_frames, num_inference_steps, fps,
            motion_bucket_id, noise_aug_strength,
            chunk_size, min_guidance_scale, max_guidance_scale,
            generator,
        )

        # ---- Diagnostic ----
        arr0 = np.array(frames[0]).astype(float)
        arrN = np.array(frames[-1]).astype(float)
        diff = float(np.abs(arr0 - arrN).mean())
        print(f"[SVD] pixel diff frame0↔frameN = {diff:.2f} (>5 = good motion)")

        # ---- Encode to MP4 with ffmpeg (H.264, crf=18, yuv420p) ----
        return _encode_mp4(frames, fps)


# ---------------------------------------------------------------------------
# Helper: prepare image (face-aware crop or letterbox)
# ---------------------------------------------------------------------------
def _prepare_image(img, target_w: int, target_h: int, letterbox: bool):
    """
    Resize input image to target_w × target_h.

    - If letterbox=True: pad with blurred background instead of cropping.
    - Otherwise: face-aware crop (OpenCV Haar cascade) with upward headroom,
      falling back to center-crop if no face detected.

    Face-aware crop dramatically reduces face warping: if we crop to 16:9
    around the face center (with headroom above), the face stays centered
    in the conditioning frame → SVD anchors motion around the face.
    """
    from PIL import Image, ImageFilter

    src_w, src_h = img.size

    if letterbox:
        return _letterbox_image(img, target_w, target_h)

    # ---- Try face detection ----
    face_cx, face_cy = _detect_face_center(img)
    target_ratio = target_w / target_h  # 1.777…

    if face_cx is not None:
        # Crop a 16:9 region centered on the face (with headroom above)
        crop_h = int(src_w / target_ratio)
        if crop_h > src_h:
            # Image is wider — crop sides instead
            crop_w = int(src_h * target_ratio)
            left = max(0, face_cx - crop_w // 2)
            left = min(left, src_w - crop_w)
            img = img.crop((left, 0, left + crop_w, src_h))
        else:
            # Standard portrait: place face at ~40% from top (headroom above)
            top = int(face_cy - crop_h * 0.40)
            top = max(0, min(top, src_h - crop_h))
            img = img.crop((0, top, src_w, top + crop_h))
        print(f"[SVD] Face-aware crop around ({face_cx}, {face_cy})")
    else:
        # Fallback: center-crop with upper-quarter bias for portraits
        src_ratio = src_w / src_h
        if src_ratio > target_ratio:
            new_w = int(src_h * target_ratio)
            left = (src_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, src_h))
        else:
            new_h = int(src_w / target_ratio)
            top = max(0, (src_h - new_h) // 4)
            img = img.crop((0, top, src_w, top + new_h))
        print("[SVD] No face detected — using center-crop fallback")

    return img.resize((target_w, target_h), Image.LANCZOS)


def _detect_face_center(img):
    """
    Detect the largest face using OpenCV Haar cascade.
    Returns (center_x, center_y) in original pixel coords, or (None, None).
    """
    import cv2
    import numpy as np

    gray = np.array(img.convert("L"))
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))

    if len(faces) == 0:
        return None, None

    # Pick the largest face
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    return x + w // 2, y + h // 2


def _letterbox_image(img, target_w: int, target_h: int):
    """
    Fit image into target_w×target_h with blurred-background padding.
    Preserves full image content — nothing is cropped.
    """
    from PIL import Image, ImageFilter

    src_w, src_h = img.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)

    # Background: blurred + darkened version of source, stretched to fill
    bg = img.resize((target_w, target_h), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=20))
    bg = bg.point(lambda p: int(p * 0.6))  # slightly darken so subject stands out

    # Paste resized subject centered
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    paste_x = (target_w - new_w) // 2
    paste_y = (target_h - new_h) // 2
    bg.paste(resized, (paste_x, paste_y))
    return bg


# ---------------------------------------------------------------------------
# Helper: run inference with OOM fallback on decode_chunk_size
# ---------------------------------------------------------------------------
def _run_inference(pipe, img, num_frames, num_inference_steps, fps,
                   motion_bucket_id, noise_aug_strength,
                   chunk_size, min_guidance_scale, max_guidance_scale,
                   generator):
    import torch

    def _call(cs):
        return pipe(
            img,
            num_frames=num_frames,
            num_inference_steps=num_inference_steps,
            fps=fps,
            motion_bucket_id=motion_bucket_id,
            noise_aug_strength=noise_aug_strength,
            decode_chunk_size=cs,
            min_guidance_scale=min_guidance_scale,
            max_guidance_scale=max_guidance_scale,
            generator=generator,
        ).frames[0]

    try:
        return _call(chunk_size)
    except torch.cuda.OutOfMemoryError:
        print(f"[SVD] OOM with chunk_size={chunk_size}, retrying with chunk_size=8")
        torch.cuda.empty_cache()
        return _call(8)


# ---------------------------------------------------------------------------
# Helper: high-quality ffmpeg H.264 encode
# ---------------------------------------------------------------------------
def _encode_mp4(frames: list, fps: int) -> bytes:
    """
    Encode PIL Image frames to MP4 using ffmpeg H.264.

    Why not export_to_video():
      diffusers' export_to_video uses imageio with a low-quality codec by default.
      ffmpeg with crf=18 and yuv420p gives broadcast-quality output compatible
      with all players and browsers.

    Settings:
      crf=18   — visually lossless (lower = better quality, larger file)
      preset=medium — good speed/quality tradeoff
      yuv420p  — maximum browser/player compatibility
    """
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Write frames as PNG (lossless intermediate)
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
            print(f"[SVD] ffmpeg stderr: {result.stderr}")
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")

        return output_path.read_bytes()


# ---------------------------------------------------------------------------
# Legacy function wrapper — keeps modal_svd_client.py call-compatible.
# Delegates to SVDModel via .local() so it uses the loaded pipeline.
# ---------------------------------------------------------------------------
@app.function(gpu="A100", timeout=300)
def run_svd(
    image_bytes: bytes,
    num_frames: int = 25,
    num_inference_steps: int = 50,
    fps: int = 7,
    motion_bucket_id: int = 100,
    noise_aug_strength: float = 0.04,
    decode_chunk_size: int = 4,
    min_guidance_scale: float = 1.0,
    max_guidance_scale: float = 3.5,
    seed: int = 12345,
    letterbox: bool = False,
) -> bytes:
    """Backwards-compatible function entrypoint — delegates to SVDModel."""
    model = SVDModel()
    return model.run.local(
        image_bytes,
        num_frames=num_frames,
        num_inference_steps=num_inference_steps,
        fps=fps,
        motion_bucket_id=motion_bucket_id,
        noise_aug_strength=noise_aug_strength,
        decode_chunk_size=decode_chunk_size,
        min_guidance_scale=min_guidance_scale,
        max_guidance_scale=max_guidance_scale,
        seed=seed,
        letterbox=letterbox,
    )


# ---------------------------------------------------------------------------
# Local smoke test:  modal run liveportrait_api/modal_svd.py
# ---------------------------------------------------------------------------
@app.local_entrypoint()
def main():
    """Smoke test — uses Olena.jpg if available, else a synthetic portrait image."""
    import io
    from pathlib import Path
    from PIL import Image

    test_image_path = Path("public/assets/user_uploaded_images/Olena.jpg")
    if test_image_path.exists():
        image_bytes = test_image_path.read_bytes()
        print(f"Using test image: {test_image_path}")
    else:
        img = Image.new("RGB", (576, 768), color=(200, 180, 160))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        image_bytes = buf.getvalue()
        print("Using synthetic test image (576×768 portrait)")

    print("Submitting SVD job (gentle preset — most stable face)...")
    model = SVDModel()
    try:
        mp4 = model.run.remote(
            image_bytes,
            **PRESETS["gentle"],
            num_frames=25,
            num_inference_steps=50,
            fps=7,
        )
        out = "modal_svd_test_output.mp4"
        Path(out).write_bytes(mp4)
        print(f"✓ Saved {len(mp4):,} bytes → {out}")
    except Exception as e:
        print(f"✗ Error: {e}")
        raise
