# coding: utf-8
"""
SmileLoop – Modal I2V client wrapper.

Provides a clean interface for calling the AnimateDiff Modal GPU function
from FastAPI.
"""

import os

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
I2V_MODAL_APP_NAME = os.environ.get("I2V_MODAL_APP_NAME", "smileloop-i2v")


class I2VError(Exception):
    """Raised when an I2V Modal call fails."""
    pass


def _get_i2v_function():
    """Lazily import and return the Modal remote I2V function."""
    try:
        import modal
        fn = modal.Function.from_name(I2V_MODAL_APP_NAME, "run_i2v")
        return fn
    except ImportError:
        raise I2VError(
            "The 'modal' package is not installed. "
            "Install it with: pip install modal"
        )
    except Exception as e:
        raise I2VError(f"Failed to connect to Modal I2V function: {e}")


def run_job(
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
    timeout: int = 300,
) -> bytes:
    """
    Submit an image-to-video job to Modal serverless GPU.

    Args:
        image_bytes:          Raw bytes of the source image (JPEG/PNG).
        prompt:               Optional text prompt to guide video generation.
        negative_prompt:      Negative prompt to avoid undesired artefacts.
        seed:                 Random seed for reproducibility (default 8888).
        num_frames:           Number of frames to generate (default 16).
        num_inference_steps:  Diffusion steps (default 50).
        guidance_scale:       CFG scale (default 9.0).
        fps:                  Output video FPS (default 8).
        timeout:              Max seconds to wait for result.

    Returns:
        Raw bytes of the output MP4.

    Raises:
        I2VError: If the Modal call fails for any reason.
    """
    fn = _get_i2v_function()

    try:
        mp4_bytes = fn.remote(
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
    except I2VError:
        raise
    except Exception as e:
        raise I2VError(f"I2V Modal inference failed: {e}")

    if not mp4_bytes:
        raise I2VError("I2V Modal returned empty result.")

    return mp4_bytes
