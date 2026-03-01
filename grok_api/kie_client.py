# coding: utf-8
"""
SmileLoop – KIE API Video Generation Client

Uses the KIE API (kie.ai) as a proxy to run Grok's "grok-imagine/image-to-video"
model.  KIE accepts external image URLs (not base64), so we upload the image to a
temp hosting service first.

Flow:
  1. Upload image to temp host → public URL
  2. POST https://api.kie.ai/api/v1/jobs/createTask  → { taskId }
  3. Poll GET  https://api.kie.ai/api/v1/jobs/recordInfo?taskId=… until state=success
  4. Download MP4 from resultUrls[0]

Usage:
    from grok_api.kie_client import kie_generate_video, KieError

    mp4_bytes = kie_generate_video(image_bytes, prompt="smiles warmly")
"""

import asyncio
import json
import os
import time
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
KIE_API_KEY = os.environ.get("KIE_API_KEY", "")
KIE_BASE_URL = "https://api.kie.ai/api/v1"
KIE_MODEL = "grok-imagine/image-to-video"

# Defaults (same as xAI for consistency)
DEFAULT_DURATION = 6         # 6 or 10 seconds
DEFAULT_RESOLUTION = "480p"  # "480p" or "720p"
DEFAULT_MODE = "normal"      # "fun", "normal", "spicy" (spicy not with external images)

# Polling
POLL_INTERVAL = 3            # seconds between status checks
POLL_TIMEOUT = 300           # max seconds (KIE can be slower than direct xAI)

# Temp image upload
TEMP_UPLOAD_URL = "https://tmpfiles.org/api/v1/upload"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class KieError(Exception):
    """Raised when a KIE API call fails."""
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


def _mime_to_ext(mime: str) -> str:
    return {"image/jpeg": "jpg", "image/png": "png"}.get(mime, "jpg")


def _validate_params(prompt: str, duration: int, resolution: str, mode: str) -> None:
    """Validate generation parameters."""
    if not prompt or not prompt.strip():
        raise KieError("Prompt cannot be empty.")
    if duration not in (6, 10):
        raise KieError(f"KIE API supports duration 6 or 10, got {duration}.")
    if resolution not in ("480p", "720p"):
        raise KieError(f"Resolution must be '480p' or '720p', got '{resolution}'.")
    if mode not in ("fun", "normal", "spicy"):
        raise KieError(f"Mode must be 'fun', 'normal', or 'spicy', got '{mode}'.")


def _auth_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _get_logger():
    """Lazy-import the API logger to avoid circular imports."""
    try:
        from webapp.api_logger import log_api_request
        return log_api_request
    except ImportError:
        return None


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Image upload to temp host (KIE needs a public URL, not base64)
# ---------------------------------------------------------------------------
def _upload_temp_image(image_bytes: bytes, mime: str) -> str:
    """
    Upload image to a temporary hosting service and return its public URL.
    Uses tmpfiles.org — files auto-expire after ~60 minutes.
    """
    ext = _mime_to_ext(mime)
    try:
        resp = httpx.post(
            TEMP_UPLOAD_URL,
            files={"file": (f"photo.{ext}", image_bytes, mime)},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        # tmpfiles.org returns {"status":"ok","data":{"url":"https://tmpfiles.org/12345/photo.jpg"}}
        raw_url = data.get("data", {}).get("url", "")
        if not raw_url:
            raise KieError(f"No URL in tmpfiles response: {data}")
        # Convert to direct-download URL: insert /dl/ after domain
        url = raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)
        print(f"  KIE: image uploaded to {url}")
        return url
    except KieError:
        raise
    except Exception as e:
        raise KieError(f"Failed to upload image to temp host: {e}")


# ---------------------------------------------------------------------------
# Core: Synchronous video generation via KIE API
# ---------------------------------------------------------------------------
def kie_generate_video(
    image_bytes: bytes,
    prompt: str,
    duration: int = DEFAULT_DURATION,
    resolution: str = DEFAULT_RESOLUTION,
    mode: str = DEFAULT_MODE,
    api_key: Optional[str] = None,
    job_id: Optional[str] = None,
    source: str = "unknown",
    **kwargs,
) -> bytes:
    """
    Generate a video from a portrait image using KIE API (Grok proxy).

    Args:
        image_bytes: Raw JPEG/PNG bytes of the source image.
        prompt: Text prompt describing the desired animation/action.
        duration: Video length — 6 or 10 seconds.
        resolution: "480p" or "720p".
        mode: "fun", "normal", or "spicy" (spicy not with external images).
        api_key: KIE API key (falls back to KIE_API_KEY env var).
        job_id: Optional SmileLoop job ID for log correlation.
        source: Caller identifier ("webapp", "cli").

    Returns:
        MP4 video bytes.

    Raises:
        KieError: If the API call fails.
    """
    log = _get_logger()
    t_start = time.time()
    submit_time_iso = _iso_now()

    key = api_key or KIE_API_KEY
    if not key:
        err = "No KIE API key configured. Set KIE_API_KEY in .env or pass api_key."
        if log:
            log(event="video_generation", job_id=job_id, source=source,
                prompt=prompt, model=KIE_MODEL, duration=duration,
                resolution=resolution, image_size_bytes=len(image_bytes),
                status="error", error=err, error_type="config",
                elapsed_seconds=time.time() - t_start,
                submit_time=submit_time_iso,
                extra={"provider": "kie"})
        raise KieError(err)

    # KIE only supports 6 or 10 second durations
    if duration not in (6, 10):
        duration = 6 if duration <= 8 else 10

    _validate_params(prompt, duration, resolution, mode)

    mime = _detect_mime(image_bytes)

    # Common log params
    log_params = dict(
        event="video_generation",
        job_id=job_id,
        source=source,
        prompt=prompt,
        model=KIE_MODEL,
        duration=duration,
        resolution=resolution,
        image_size_bytes=len(image_bytes),
        image_mime=mime,
        submit_time=submit_time_iso,
        extra={"provider": "kie", "mode": mode},
    )

    # ── Step 1: Upload image to get a public URL ──
    print(f"  KIE: uploading image ({len(image_bytes):,} bytes)…")
    try:
        image_url = _upload_temp_image(image_bytes, mime)
    except KieError as e:
        if log:
            log(**log_params, status="error", error=str(e),
                error_type="upload_failed", elapsed_seconds=time.time() - t_start,
                complete_time=_iso_now())
        raise

    # ── Step 2: Create task ──
    headers = _auth_headers(key)
    payload = {
        "model": KIE_MODEL,
        "input": {
            "image_urls": [image_url],
            "prompt": prompt.strip(),
            "mode": mode,
            "duration": str(duration),
            "resolution": resolution,
        },
    }

    print(f"  KIE: creating task ({duration}s, {resolution}, mode={mode})…")
    try:
        resp = httpx.post(
            f"{KIE_BASE_URL}/jobs/createTask",
            headers=headers,
            json=payload,
            timeout=30,
        )
    except Exception as e:
        if log:
            log(**log_params, status="error", error=str(e),
                error_type="create_task_failed", elapsed_seconds=time.time() - t_start,
                complete_time=_iso_now())
        raise KieError(f"Failed to create KIE task: {e}")

    if resp.status_code != 200:
        err = f"KIE createTask failed (HTTP {resp.status_code}): {resp.text[:500]}"
        if log:
            log(**log_params, status="error", error=err,
                error_type="http_error", elapsed_seconds=time.time() - t_start,
                complete_time=_iso_now())
        raise KieError(err)

    data = resp.json()
    if data.get("code") != 200:
        err = f"KIE createTask error: {data.get('message', 'unknown')}"
        if log:
            log(**log_params, status="error", error=err,
                error_type="api_error", elapsed_seconds=time.time() - t_start,
                complete_time=_iso_now())
        raise KieError(err)

    task_id = data.get("data", {}).get("taskId")
    if not task_id:
        err = f"No taskId in KIE response: {data}"
        if log:
            log(**log_params, status="error", error=err,
                error_type="missing_task_id", elapsed_seconds=time.time() - t_start,
                complete_time=_iso_now())
        raise KieError(err)

    print(f"  KIE: task created — taskId={task_id}")

    # ── Step 3: Poll for completion ──
    result_url = _poll_until_ready(task_id, key)

    # ── Step 4: Download the video ──
    print(f"  KIE: downloading video from {result_url[:80]}…")
    video_bytes = _download_video(result_url)

    if not video_bytes:
        if log:
            log(**log_params, status="error", error="Downloaded video is empty",
                error_type="empty_download", video_url=result_url,
                elapsed_seconds=time.time() - t_start, complete_time=_iso_now())
        raise KieError("Downloaded video is empty.")

    elapsed = time.time() - t_start
    print(f"  KIE: done — {len(video_bytes):,} bytes ({elapsed:.1f}s total)")

    # ── Log success ──
    if log:
        log(**log_params,
            status="success",
            video_url=result_url,
            video_size_bytes=len(video_bytes),
            elapsed_seconds=elapsed,
            complete_time=_iso_now())

    return video_bytes


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------
def _poll_until_ready(task_id: str, api_key: str) -> str:
    """
    Poll KIE API until the task completes.
    Returns the video download URL.
    """
    headers = _auth_headers(api_key)
    url = f"{KIE_BASE_URL}/jobs/recordInfo"
    start = time.time()

    with httpx.Client(timeout=30) as client:
        while True:
            elapsed = time.time() - start
            if elapsed > POLL_TIMEOUT:
                raise KieError(
                    f"KIE task timed out after {POLL_TIMEOUT}s (taskId={task_id})"
                )

            try:
                resp = client.get(url, headers=headers, params={"taskId": task_id})
            except Exception as e:
                print(f"  KIE: poll error ({e}), retrying…")
                time.sleep(POLL_INTERVAL)
                continue

            if resp.status_code != 200:
                print(f"  KIE: poll HTTP {resp.status_code}, retrying…")
                time.sleep(POLL_INTERVAL)
                continue

            data = resp.json()
            task_data = data.get("data", {})
            state = task_data.get("state", "")

            if state == "success":
                # Parse resultJson — it's a JSON string
                result_json_str = task_data.get("resultJson", "{}")
                try:
                    result_json = json.loads(result_json_str) if isinstance(result_json_str, str) else result_json_str
                except json.JSONDecodeError:
                    raise KieError(f"Invalid resultJson: {result_json_str[:200]}")

                result_urls = result_json.get("resultUrls", [])
                if not result_urls:
                    raise KieError(f"No resultUrls in KIE response: {result_json}")

                print(f"  KIE: task complete — {elapsed:.1f}s elapsed")
                return result_urls[0]

            elif state == "fail":
                fail_msg = task_data.get("failMsg", "Unknown error")
                raise KieError(f"KIE task failed: {fail_msg}")

            else:
                # Still processing
                time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Async variant
# ---------------------------------------------------------------------------
async def kie_generate_video_async(
    image_bytes: bytes,
    prompt: str,
    duration: int = DEFAULT_DURATION,
    resolution: str = DEFAULT_RESOLUTION,
    mode: str = DEFAULT_MODE,
    api_key: Optional[str] = None,
    job_id: Optional[str] = None,
    source: str = "webapp",
    **kwargs,
) -> bytes:
    """Async version of kie_generate_video for use in FastAPI."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: kie_generate_video(
            image_bytes=image_bytes,
            prompt=prompt,
            duration=duration,
            resolution=resolution,
            mode=mode,
            api_key=api_key,
            job_id=job_id,
            source=source,
        ),
    )


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------
def _download_video(url: str) -> bytes:
    """Download video from a URL."""
    try:
        resp = httpx.get(url, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        raise KieError(f"Failed to download video: {e}")
