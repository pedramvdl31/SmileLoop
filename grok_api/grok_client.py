# coding: utf-8
"""
SmileLoop – Grok (xAI) Video Generation Client

Uses the xAI SDK (xai_sdk) with model "grok-imagine-video" to generate
a short video from a portrait photo + text prompt.

The SDK uses gRPC under the hood which correctly transmits the base64 image
so the generated video actually features the uploaded person.

Every API call is logged to logs/api_requests_YYYY-MM-DD.jsonl with full
request params, response details, timing, and errors.

Usage:
    from grok_api.grok_client import grok_generate_video, GrokError

    mp4_bytes = grok_generate_video(image_bytes, prompt="smiles warmly")
"""

import asyncio
import base64
import os
import time
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
GROK_VIDEO_MODEL = "grok-imagine-video"

# Defaults
DEFAULT_DURATION = 6         # seconds (1–15)
DEFAULT_RESOLUTION = "480p"  # "480p" or "720p"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class GrokError(Exception):
    """Raised when a Grok API call fails."""
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _detect_mime(image_bytes: bytes) -> str:
    """Detect MIME type from image magic bytes."""
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


def _validate_params(prompt: str, duration: int, resolution: str) -> None:
    """Validate generation parameters."""
    if not prompt or not prompt.strip():
        raise GrokError("Prompt cannot be empty.")
    if not 1 <= duration <= 15:
        raise GrokError(f"Duration must be 1–15 seconds, got {duration}.")
    if resolution not in ("480p", "720p"):
        raise GrokError(f"Resolution must be '480p' or '720p', got '{resolution}'.")


def _get_logger():
    """Lazy-import the API logger to avoid circular imports."""
    try:
        from webapp.api_logger import log_api_request
        return log_api_request
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Core: Synchronous video generation via xAI SDK (gRPC)
# ---------------------------------------------------------------------------
def grok_generate_video(
    image_bytes: bytes,
    prompt: str,
    duration: int = DEFAULT_DURATION,
    resolution: str = DEFAULT_RESOLUTION,
    api_key: Optional[str] = None,
    job_id: Optional[str] = None,
    source: str = "unknown",
    **kwargs,
) -> bytes:
    """
    Generate a video from a portrait image using Grok's video model.

    Uses the xai_sdk which communicates via gRPC — this correctly transmits
    base64 image data so the video features the actual uploaded person.

    Args:
        image_bytes: Raw JPEG/PNG bytes of the source image.
        prompt: Text prompt describing the desired animation/action.
        duration: Video length in seconds (1–15, default 6).
        resolution: "480p" ($0.05/sec) or "720p" ($0.07/sec).
        api_key: xAI API key (falls back to XAI_API_KEY env var).
        job_id: Optional SmileLoop job ID for log correlation.
        source: Caller identifier (e.g. "webapp", "cli").

    Returns:
        MP4 video bytes (with audio).

    Raises:
        GrokError: If the API call fails.
    """
    log = _get_logger()
    t_start = time.time()
    submit_time_iso = _iso_now()

    key = api_key or XAI_API_KEY
    if not key:
        err = "No xAI API key configured. Set XAI_API_KEY in .env or pass api_key."
        if log:
            log(event="video_generation", job_id=job_id, source=source,
                prompt=prompt, model=GROK_VIDEO_MODEL, duration=duration,
                resolution=resolution, image_size_bytes=len(image_bytes),
                image_mime=_detect_mime(image_bytes),
                status="error", error=err, error_type="config",
                elapsed_seconds=time.time() - t_start,
                submit_time=submit_time_iso)
        raise GrokError(err)

    _validate_params(prompt, duration, resolution)

    # Encode image as base64 data URI
    mime = _detect_mime(image_bytes)
    b64_data = base64.b64encode(image_bytes).decode("utf-8")
    image_url = f"data:{mime};base64,{b64_data}"

    # Common log params
    log_params = dict(
        event="video_generation",
        job_id=job_id,
        source=source,
        prompt=prompt,
        model=GROK_VIDEO_MODEL,
        duration=duration,
        resolution=resolution,
        image_size_bytes=len(image_bytes),
        image_mime=mime,
        submit_time=submit_time_iso,
    )

    # Use the xAI SDK (gRPC) — this correctly sends the image
    response = None
    try:
        os.environ["XAI_API_KEY"] = key
        from xai_sdk import Client

        client = Client()
        print(f"  Grok SDK: generating video ({duration}s, {resolution})…")
        response = client.video.generate(
            prompt=prompt.strip(),
            model=GROK_VIDEO_MODEL,
            image_url=image_url,
            duration=duration,
            resolution=resolution,
        )
    except GrokError:
        raise
    except Exception as e:
        elapsed = time.time() - t_start
        if log:
            log(**log_params, status="error", error=str(e),
                error_type=type(e).__name__, elapsed_seconds=elapsed,
                complete_time=_iso_now())
        raise GrokError(f"Grok video generation failed: {e}")

    # Extract SDK response metadata
    video_url = None
    resp_model = None
    resp_duration = None
    resp_moderation = None

    try:
        video_url = response.url
    except (ValueError, AttributeError) as e:
        elapsed = time.time() - t_start
        if log:
            log(**log_params, status="error",
                error=f"Could not get video URL: {e}",
                error_type=type(e).__name__, elapsed_seconds=elapsed,
                complete_time=_iso_now())
        raise GrokError(f"Could not get video URL from SDK response: {e}")

    # Safely extract optional response fields
    try:
        resp_model = response.model
    except Exception:
        pass
    try:
        resp_duration = response.duration
    except Exception:
        pass
    try:
        resp_moderation = response.respect_moderation
    except Exception:
        pass

    if not video_url:
        elapsed = time.time() - t_start
        if log:
            log(**log_params, status="error", error="Empty video URL",
                error_type="empty_response", elapsed_seconds=elapsed,
                complete_time=_iso_now())
        raise GrokError("Grok SDK returned empty video URL.")

    print(f"  Grok SDK: video ready, downloading from {video_url[:80]}…")
    video_bytes = _download_video(video_url)

    if not video_bytes:
        elapsed = time.time() - t_start
        if log:
            log(**log_params, status="error", error="Downloaded video is empty",
                error_type="empty_download", video_url=video_url,
                elapsed_seconds=elapsed, complete_time=_iso_now())
        raise GrokError("Downloaded video is empty.")

    elapsed = time.time() - t_start
    print(f"  Grok SDK: downloaded {len(video_bytes):,} bytes ({elapsed:.1f}s total)")

    # ── Log success ──
    if log:
        log(**log_params,
            status="success",
            video_url=video_url,
            video_size_bytes=len(video_bytes),
            video_duration=resp_duration,
            respect_moderation=resp_moderation,
            response_model=resp_model,
            elapsed_seconds=elapsed,
            complete_time=_iso_now())

    return video_bytes


# ---------------------------------------------------------------------------
# Async variant (runs sync SDK call in a thread executor)
# ---------------------------------------------------------------------------
async def grok_generate_video_async(
    image_bytes: bytes,
    prompt: str,
    duration: int = DEFAULT_DURATION,
    resolution: str = DEFAULT_RESOLUTION,
    api_key: Optional[str] = None,
    job_id: Optional[str] = None,
    source: str = "webapp",
    **kwargs,
) -> bytes:
    """
    Async version of grok_generate_video for use in FastAPI.

    Runs the synchronous SDK call in a thread executor so it doesn't
    block the event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: grok_generate_video(
            image_bytes=image_bytes,
            prompt=prompt,
            duration=duration,
            resolution=resolution,
            api_key=api_key,
            job_id=job_id,
            source=source,
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _iso_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _download_video(url: str) -> bytes:
    """Download video from a URL."""
    try:
        resp = httpx.get(url, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        raise GrokError(f"Failed to download Grok video: {e}")
