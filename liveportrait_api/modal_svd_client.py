# coding: utf-8
"""
SmileLoop – Modal SVD client wrapper.

Provides a clean interface for calling the SVD Modal GPU function from FastAPI.
"""

import os

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SVD_MODAL_APP_NAME = os.environ.get("SVD_MODAL_APP_NAME", "smileloop-svd")


class SVDError(Exception):
    """Raised when an SVD Modal call fails."""
    pass


def _get_svd_function():
    """Lazily import and return the Modal remote SVD function."""
    try:
        import modal
        fn = modal.Function.from_name(SVD_MODAL_APP_NAME, "run_svd")
        return fn
    except ImportError:
        raise SVDError(
            "The 'modal' package is not installed. "
            "Install it with: pip install modal"
        )
    except Exception as e:
        raise SVDError(f"Failed to connect to Modal SVD function: {e}")


def run_job(
    image_bytes: bytes,
    num_frames: int = 25,
    num_inference_steps: int = 30,
    fps: int = 7,
    motion_bucket_id: int = 120,
    noise_aug_strength: float = 0.06,
    decode_chunk_size: int = -1,   # -1 = auto (all frames at once, with OOM fallback to 8)
    min_guidance_scale: float = 1.0,
    max_guidance_scale: float = 5.0,
    seed: int = 12345,
    letterbox: bool = False,
    timeout: int = 300,
) -> bytes:
    """
    Submit an SVD animation job to Modal serverless GPU.

    Args:
        image_bytes:           Raw bytes of the source image (JPEG/PNG).
        num_frames:            Number of frames to generate (default 25).
        num_inference_steps:   Diffusion steps (default 30).
        fps:                   Output video FPS (default 7 → ~3.5s clip).
        motion_bucket_id:      Motion amount 1-255 (default 120 = moderate, portrait-safe).
        noise_aug_strength:    Noise on conditioning frame (default 0.06 = low, preserves identity).
        decode_chunk_size:     -1 = decode all frames together (best quality, no ghosting).
                               Falls back to 8 automatically on OOM.
        min_guidance_scale:    CFG on first frame (default 1.0).
        max_guidance_scale:    CFG on last frame (default 5.0). Higher = anchors face identity.
        seed:                  RNG seed for reproducibility (default 12345).
        letterbox:             If True, pad with blurred background instead of cropping.
        timeout:               Max seconds to wait for result.

    Returns:
        Raw bytes of the output MP4.

    Raises:
        SVDError: If the Modal call fails for any reason.
    """
    fn = _get_svd_function()

    try:
        mp4_bytes = fn.remote(
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
    except SVDError:
        raise
    except Exception as e:
        raise SVDError(f"SVD Modal inference failed: {e}")

    if not mp4_bytes:
        raise SVDError("SVD Modal returned empty result.")

    return mp4_bytes
