# coding: utf-8
"""
SmileLoop – API Request Logger

Logs every xAI API request/response to a JSONL file (one JSON object per line).
Each entry captures: timestamp, prompt, settings, image info, SDK response,
timing, output size, errors, and job context.

Log file: logs/api_requests.jsonl  (auto-created, rotated by date)
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = _PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Lock for thread-safe writes
_write_lock = threading.Lock()


def _log_path() -> Path:
    """Return today's log file path: logs/api_requests_YYYY-MM-DD.jsonl"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    return LOGS_DIR / f"api_requests_{date_str}.jsonl"


def _now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def log_api_request(
    *,
    event: str = "video_generation",
    job_id: Optional[str] = None,
    source: str = "unknown",
    # Request params
    prompt: Optional[str] = None,
    model: Optional[str] = None,
    duration: Optional[int] = None,
    resolution: Optional[str] = None,
    image_size_bytes: Optional[int] = None,
    image_mime: Optional[str] = None,
    # Response
    status: str = "unknown",
    video_url: Optional[str] = None,
    video_size_bytes: Optional[int] = None,
    video_duration: Optional[int] = None,
    respect_moderation: Optional[bool] = None,
    response_model: Optional[str] = None,
    # Timing
    elapsed_seconds: Optional[float] = None,
    submit_time: Optional[str] = None,
    complete_time: Optional[str] = None,
    # Error
    error: Optional[str] = None,
    error_type: Optional[str] = None,
    # Extra
    extra: Optional[dict] = None,
) -> dict:
    """
    Log an API request entry. Writes a JSON line to the daily log file.

    Returns the logged entry dict.
    """
    entry = {
        "timestamp": _now_iso(),
        "event": event,
        "job_id": job_id,
        "source": source,
        # Request
        "request": {
            "prompt": prompt,
            "model": model,
            "duration": duration,
            "resolution": resolution,
            "image_size_bytes": image_size_bytes,
            "image_mime": image_mime,
        },
        # Response
        "response": {
            "status": status,
            "video_url": video_url,
            "video_size_bytes": video_size_bytes,
            "video_duration": video_duration,
            "respect_moderation": respect_moderation,
            "response_model": response_model,
        },
        # Timing
        "timing": {
            "elapsed_seconds": round(elapsed_seconds, 2) if elapsed_seconds is not None else None,
            "submit_time": submit_time,
            "complete_time": complete_time,
        },
        # Error
        "error": {
            "message": error,
            "type": error_type,
        } if error else None,
    }

    # Merge any extra data
    if extra:
        entry["extra"] = extra

    # Remove None-valued top-level keys for cleaner logs
    entry = {k: v for k, v in entry.items() if v is not None}

    _write_entry(entry)
    return entry


def log_webapp_request(
    *,
    event: str,
    job_id: Optional[str] = None,
    method: str = "",
    path: str = "",
    status_code: Optional[int] = None,
    client_ip: Optional[str] = None,
    prompt: Optional[str] = None,
    animation: Optional[str] = None,
    email: Optional[str] = None,
    elapsed_seconds: Optional[float] = None,
    error: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    """
    Log a webapp-level request (upload, status poll, payment, download, etc.).
    """
    entry = {
        "timestamp": _now_iso(),
        "event": event,
        "job_id": job_id,
        "http": {
            "method": method,
            "path": path,
            "status_code": status_code,
            "client_ip": client_ip,
        },
    }

    if prompt:
        entry["prompt"] = prompt
    if animation:
        entry["animation"] = animation
    if email:
        entry["email"] = _mask_email(email)
    if elapsed_seconds is not None:
        entry["elapsed_seconds"] = round(elapsed_seconds, 2)
    if error:
        entry["error"] = error
    if extra:
        entry["extra"] = extra

    _write_entry(entry)
    return entry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mask_email(email: str) -> str:
    """Mask email for privacy: pedram@gmail.com → p***m@gmail.com"""
    if not email or "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    if len(local) <= 2:
        masked = local[0] + "***"
    else:
        masked = local[0] + "***" + local[-1]
    return f"{masked}@{domain}"


def _write_entry(entry: dict) -> None:
    """Thread-safe write of a JSON line to the log file."""
    path = _log_path()
    line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"

    with _write_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)


def get_recent_logs(n: int = 50) -> list[dict]:
    """Read the last N log entries from today's log file."""
    path = _log_path()
    if not path.exists():
        return []

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in lines[-n:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries
