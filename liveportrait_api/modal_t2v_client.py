# coding: utf-8
"""
SmileLoop – Modal T2V client wrapper.

Provides a clean interface for calling the ModelScope Text-to-Video
Modal GPU function from FastAPI.
"""

import os

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
T2V_MODAL_APP_NAME = os.environ.get("T2V_MODAL_APP_NAME", "smileloop-t2v")


class T2VError(Exception):
    """Raised when a T2V Modal call fails."""
    pass


def _get_t2v_function():
    """Lazily import and return the Modal remote T2V function."""
    try:
        import modal
        fn = modal.Function.from_name(T2V_MODAL_APP_NAME, "run_t2v")
        return fn
    except ImportError:
        raise T2VError(
            "The 'modal' package is not installed. "
            "Install it with: pip install modal"
        )
    except Exception as e:
        raise T2VError(f"Failed to connect to Modal T2V function: {e}")


def run_job(
    prompt: str,
    seed: int = -1,
    num_frames: int = 16,
    num_inference_steps: int = 50,
    fps: int = 8,
    timeout: int = 300,
) -> bytes:
    """
    Submit a text-to-video job to Modal serverless GPU.

    Args:
        prompt:               English text description.
        seed:                 Random seed (-1 = random). >=0 for reproducible.
        num_frames:           Number of frames to generate (default 16).
        num_inference_steps:  Diffusion steps (default 50, higher = better quality).
        fps:                  Output video FPS (default 8).
        timeout:              Max seconds to wait for result.

    Returns:
        Raw bytes of the output MP4.

    Raises:
        T2VError: If the Modal call fails for any reason.
    """
    fn = _get_t2v_function()

    try:
        mp4_bytes = fn.remote(
            prompt,
            seed=seed,
            num_frames=num_frames,
            num_inference_steps=num_inference_steps,
            fps=fps,
        )
    except T2VError:
        raise
    except Exception as e:
        raise T2VError(f"T2V Modal inference failed: {e}")

    if not mp4_bytes:
        raise T2VError("T2V Modal returned empty result.")

    return mp4_bytes
