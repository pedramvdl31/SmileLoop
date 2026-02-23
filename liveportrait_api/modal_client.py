# coding: utf-8
"""
SmileLoop – Modal client wrapper.

Provides a clean interface for calling the Modal GPU function from FastAPI.
Handles preset syncing, error wrapping, and fallback logic.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODAL_APP_NAME = os.environ.get("MODAL_APP_NAME", "smileloop-liveportrait")


class ModalError(Exception):
    """Raised when a Modal call fails."""
    pass


def _get_modal_function():
    """
    Lazily import and return the Modal remote function.
    This avoids importing modal at module level (which would fail
    if modal is not installed, e.g. on the GPU server running local mode).
    """
    try:
        import modal
        fn = modal.Function.from_name(MODAL_APP_NAME, "run_liveportrait")
        return fn
    except ImportError:
        raise ModalError(
            "The 'modal' package is not installed. "
            "Install it with: pip install modal"
        )
    except Exception as e:
        raise ModalError(f"Failed to connect to Modal function: {e}")


def run_job(
    image_bytes: bytes,
    preset: str,
    driving_video_path: Path | None = None,
    timeout: int = 300,
) -> bytes:
    """
    Submit an animation job to Modal serverless GPU.

    Args:
        image_bytes:        Raw bytes of the source portrait (JPEG/PNG).
        preset:             Name of the driving-motion preset (e.g. "d6_1s").
        driving_video_path: Path to the local .mp4 driving video.
                            Sent on the first call so Modal caches it.
        timeout:            Max seconds to wait for the result.

    Returns:
        Raw bytes of the output MP4.

    Raises:
        ModalError: If the Modal call fails for any reason.
    """
    fn = _get_modal_function()

    # Read driving video bytes if path is provided
    driving_video_bytes = None
    if driving_video_path and driving_video_path.exists():
        driving_video_bytes = driving_video_path.read_bytes()

    try:
        mp4_bytes = fn.remote(
            image_bytes,
            preset,
            driving_video_bytes=driving_video_bytes,
        )
    except ModalError:
        raise
    except Exception as e:
        raise ModalError(f"Modal inference failed: {e}")

    if not mp4_bytes:
        raise ModalError("Modal returned empty result.")

    return mp4_bytes
