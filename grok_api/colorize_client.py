# coding: utf-8
"""
SmileLoop – Colorize Pipeline Client (KIE API)

Two-step pipeline:
  1. Image-to-Image (colorize)  → grok-imagine/image-to-image
  2. Image-to-Video (animate)   → grok-imagine/image-to-video

Both steps go through the KIE API, which uses the same task flow:
  POST /api/v1/jobs/createTask → poll GET /api/v1/jobs/recordInfo?taskId=…

Usage:
    from grok_api.colorize_client import colorize_and_animate, ColorizeError

    # Full pipeline — returns (colorized_image_bytes, mp4_bytes)
    color_img, video = colorize_and_animate(bw_image_bytes, video_prompt="smiles warmly")

    # Colorize only
    from grok_api.colorize_client import colorize_image
    color_img = colorize_image(bw_image_bytes, prompt="Colorize this photo with vivid natural colors")
"""

import json
import os
import time
from typing import Optional, Tuple

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
KIE_API_KEY = os.environ.get("KIE_API_KEY", "")
KIE_BASE_URL = "https://api.kie.ai/api/v1"

MODEL_I2I = "grok-imagine/image-to-image"
MODEL_I2V = "grok-imagine/image-to-video"

DEFAULT_COLORIZE_PROMPT = (
    "Colorize this black and white photograph with natural, realistic, vivid colors. "
    "Preserve all original details, textures, and lighting."
)

# Video defaults
DEFAULT_DURATION = 6
DEFAULT_RESOLUTION = "480p"
DEFAULT_MODE = "normal"

# Polling
POLL_INTERVAL = 3
POLL_TIMEOUT = 300

# Temp image upload
TEMP_UPLOAD_URL = "https://tmpfiles.org/api/v1/upload"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ColorizeError(Exception):
    """Raised when the colorize pipeline fails."""
    pass


# ---------------------------------------------------------------------------
# Helpers (shared with kie_client but kept standalone for independence)
# ---------------------------------------------------------------------------
def _detect_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


def _mime_to_ext(mime: str) -> str:
    return {"image/jpeg": "jpg", "image/png": "png"}.get(mime, "jpg")


def _auth_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _upload_temp_image(image_bytes: bytes, mime: str) -> str:
    """Upload image to tmpfiles.org and return a direct-download URL."""
    ext = _mime_to_ext(mime)
    try:
        resp = httpx.post(
            TEMP_UPLOAD_URL,
            files={"file": (f"photo.{ext}", image_bytes, mime)},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_url = data.get("data", {}).get("url", "")
        if not raw_url:
            raise ColorizeError(f"No URL in tmpfiles response: {data}")
        url = raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)
        return url
    except ColorizeError:
        raise
    except Exception as e:
        raise ColorizeError(f"Failed to upload image to temp host: {e}")


def _create_task(payload: dict, api_key: str) -> str:
    """POST createTask and return taskId."""
    headers = _auth_headers(api_key)
    try:
        resp = httpx.post(
            f"{KIE_BASE_URL}/jobs/createTask",
            headers=headers,
            json=payload,
            timeout=30,
        )
    except Exception as e:
        raise ColorizeError(f"Failed to create task: {e}")

    if resp.status_code != 200:
        raise ColorizeError(f"createTask HTTP {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    if data.get("code") != 200:
        raise ColorizeError(f"createTask error: {data.get('message', 'unknown')}")

    task_id = data.get("data", {}).get("taskId")
    if not task_id:
        raise ColorizeError(f"No taskId in response: {data}")
    return task_id


def _poll_until_ready(task_id: str, api_key: str, label: str = "task") -> list:
    """
    Poll recordInfo until state=success.
    Returns the list of resultUrls.
    """
    headers = _auth_headers(api_key)
    url = f"{KIE_BASE_URL}/jobs/recordInfo"
    start = time.time()

    with httpx.Client(timeout=30) as client:
        while True:
            elapsed = time.time() - start
            if elapsed > POLL_TIMEOUT:
                raise ColorizeError(f"{label} timed out after {POLL_TIMEOUT}s (taskId={task_id})")

            try:
                resp = client.get(url, headers=headers, params={"taskId": task_id})
            except Exception as e:
                print(f"  [{label}] poll error ({e}), retrying…")
                time.sleep(POLL_INTERVAL)
                continue

            if resp.status_code != 200:
                print(f"  [{label}] poll HTTP {resp.status_code}, retrying…")
                time.sleep(POLL_INTERVAL)
                continue

            data = resp.json()
            task_data = data.get("data", {})
            state = task_data.get("state", "")

            if state == "success":
                result_json_str = task_data.get("resultJson", "{}")
                try:
                    result_json = json.loads(result_json_str) if isinstance(result_json_str, str) else result_json_str
                except json.JSONDecodeError:
                    raise ColorizeError(f"Invalid resultJson: {result_json_str[:200]}")

                result_urls = result_json.get("resultUrls", [])
                if not result_urls:
                    raise ColorizeError(f"No resultUrls in response: {result_json}")

                print(f"  [{label}] complete — {elapsed:.1f}s")
                return result_urls

            elif state == "fail":
                fail_msg = task_data.get("failMsg", "Unknown error")
                raise ColorizeError(f"{label} failed: {fail_msg}")

            else:
                time.sleep(POLL_INTERVAL)


def _download(url: str) -> bytes:
    """Download content from a URL."""
    try:
        resp = httpx.get(url, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        raise ColorizeError(f"Failed to download from {url[:80]}: {e}")


# ---------------------------------------------------------------------------
# Step 1: Colorize (image-to-image)
# ---------------------------------------------------------------------------
def colorize_image(
    image_bytes: bytes,
    prompt: str = DEFAULT_COLORIZE_PROMPT,
    api_key: Optional[str] = None,
    image_index: int = 0,
) -> Tuple[bytes, list]:
    """
    Colorize a B&W image via KIE image-to-image.

    Args:
        image_bytes: Raw JPEG/PNG bytes of the B&W source image.
        prompt: Prompt for colorization (has good default).
        api_key: KIE API key (falls back to KIE_API_KEY env var).
        image_index: Which result image to use (0 or 1; API returns 2).

    Returns:
        Tuple of (colorized_image_bytes, all_result_urls).

    Raises:
        ColorizeError on failure.
    """
    key = api_key or KIE_API_KEY
    if not key:
        raise ColorizeError("No KIE API key. Set KIE_API_KEY or pass api_key.")

    mime = _detect_mime(image_bytes)

    # Upload image
    print(f"  [colorize] uploading image ({len(image_bytes):,} bytes)…")
    image_url = _upload_temp_image(image_bytes, mime)
    print(f"  [colorize] uploaded → {image_url}")

    # Create task
    payload = {
        "model": MODEL_I2I,
        "input": {
            "prompt": prompt.strip(),
            "image_urls": [image_url],
        },
    }

    print(f"  [colorize] creating task…")
    task_id = _create_task(payload, key)
    print(f"  [colorize] taskId={task_id}")

    # Poll
    result_urls = _poll_until_ready(task_id, key, label="colorize")
    print(f"  [colorize] got {len(result_urls)} result image(s)")

    # Download the chosen image
    idx = min(image_index, len(result_urls) - 1)
    color_url = result_urls[idx]
    print(f"  [colorize] downloading image #{idx} from {color_url[:80]}…")
    color_bytes = _download(color_url)

    if not color_bytes:
        raise ColorizeError("Downloaded colorized image is empty.")

    print(f"  [colorize] done — {len(color_bytes):,} bytes")
    return color_bytes, result_urls


# ---------------------------------------------------------------------------
# Step 2: Animate (image-to-video) – reuses the same KIE task flow
# ---------------------------------------------------------------------------
def animate_image(
    image_url: str,
    prompt: str = "smiles warmly and naturally",
    duration: int = DEFAULT_DURATION,
    resolution: str = DEFAULT_RESOLUTION,
    mode: str = DEFAULT_MODE,
    api_key: Optional[str] = None,
) -> bytes:
    """
    Generate video from an image URL via KIE image-to-video.

    This takes an already-public URL (e.g. from the colorize step)
    so no upload is needed.

    Args:
        image_url: Public URL of the colorized image.
        prompt: Video animation prompt.
        duration: 6 or 10 seconds.
        resolution: "480p" or "720p".
        mode: "fun", "normal", or "spicy".
        api_key: KIE API key.

    Returns:
        MP4 video bytes.
    """
    key = api_key or KIE_API_KEY
    if not key:
        raise ColorizeError("No KIE API key. Set KIE_API_KEY or pass api_key.")

    if duration not in (6, 10):
        duration = 6 if duration <= 8 else 10

    payload = {
        "model": MODEL_I2V,
        "input": {
            "image_urls": [image_url],
            "prompt": prompt.strip(),
            "mode": mode,
            "duration": str(duration),
            "resolution": resolution,
        },
    }

    print(f"  [animate] creating task ({duration}s, {resolution}, mode={mode})…")
    task_id = _create_task(payload, key)
    print(f"  [animate] taskId={task_id}")

    result_urls = _poll_until_ready(task_id, key, label="animate")
    video_url = result_urls[0]

    print(f"  [animate] downloading video from {video_url[:80]}…")
    video_bytes = _download(video_url)

    if not video_bytes:
        raise ColorizeError("Downloaded video is empty.")

    print(f"  [animate] done — {len(video_bytes):,} bytes")
    return video_bytes


# ---------------------------------------------------------------------------
# Full pipeline: Colorize → Animate
# ---------------------------------------------------------------------------
def colorize_and_animate(
    image_bytes: bytes,
    colorize_prompt: str = DEFAULT_COLORIZE_PROMPT,
    video_prompt: str = "smiles warmly and naturally",
    duration: int = DEFAULT_DURATION,
    resolution: str = DEFAULT_RESOLUTION,
    mode: str = DEFAULT_MODE,
    api_key: Optional[str] = None,
    image_index: int = 0,
) -> Tuple[bytes, bytes]:
    """
    Full pipeline: colorize a B&W image, then animate it into a video.

    Args:
        image_bytes: Raw JPEG/PNG of the B&W source.
        colorize_prompt: Prompt for image-to-image colorization.
        video_prompt: Prompt for the video animation.
        duration: Video duration (6 or 10).
        resolution: "480p" or "720p".
        mode: "fun", "normal", or "spicy".
        api_key: KIE API key.
        image_index: Which colorized image to use (0 or 1).

    Returns:
        Tuple of (colorized_image_bytes, mp4_video_bytes).
    """
    t_start = time.time()

    # Step 1: Colorize
    print("═══ Step 1: Colorize ═══")
    color_bytes, result_urls = colorize_image(
        image_bytes, prompt=colorize_prompt, api_key=api_key, image_index=image_index,
    )

    # The colorized image is already hosted on KIE's CDN — use that URL directly
    color_url = result_urls[min(image_index, len(result_urls) - 1)]

    # Step 2: Animate
    print("═══ Step 2: Animate ═══")
    video_bytes = animate_image(
        image_url=color_url,
        prompt=video_prompt,
        duration=duration,
        resolution=resolution,
        mode=mode,
        api_key=api_key,
    )

    elapsed = time.time() - t_start
    print(f"═══ Pipeline complete — {elapsed:.1f}s total ═══")

    return color_bytes, video_bytes
