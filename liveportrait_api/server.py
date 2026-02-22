# coding: utf-8
"""
SmileLoop – FastAPI backend  (Phase 1, local dev)

Upload a portrait → pick a preset motion → get an animated MP4.
Wraps KlingAIResearch/LivePortrait inference without modifying its code.

Business flow handled here:
  POST /animate  →  returns watermarked preview  (free)
  GET  /download/{job_id}  →  returns clean MP4   (pay-gated later)
"""

import asyncio
import json
import os
import shutil
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
import importlib.util
import io
import time as time_mod

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
API_DIR = Path(__file__).resolve().parent                    # liveportrait_api/
PROJECT_ROOT = API_DIR.parent                                # SmileLoop repo root
PRESETS_DIR = API_DIR / "presets"                             # driving-motion clips
JOBS_DIR = API_DIR / "jobs"                                  # temp upload + output area

# LivePortrait repo location – set via env var, default = sibling folder
LIVEPORTRAIT_ROOT = Path(
    os.environ.get("LIVEPORTRAIT_ROOT", str(PROJECT_ROOT / "LivePortrait"))
).resolve()
INFERENCE_SCRIPT = LIVEPORTRAIT_ROOT / "inference.py"

# ---------------------------------------------------------------------------
# Preset registry – auto-discovers every .mp4 in the presets folder.
# The preset name is the filename without extension.
#   e.g.  presets/gentle_smile.mp4  →  preset name "gentle_smile"
# Drop in new .mp4 files and restart the server to add more presets.
# ---------------------------------------------------------------------------
def _discover_presets() -> dict[str, Path]:
    """Scan the presets directory and return {name: path} for every .mp4."""
    if not PRESETS_DIR.exists():
        return {}
    return {f.stem: f for f in sorted(PRESETS_DIR.glob("*.mp4"))}

PRESETS = _discover_presets()

# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------
MAX_FILE_SIZE = 10 * 1024 * 1024          # 10 MB
MAGIC_JPEG = b"\xff\xd8\xff"
MAGIC_PNG  = b"\x89PNG\r\n\x1a\n"
JOB_TTL_SECONDS = 60 * 60                # auto-delete jobs older than 1 hour

# ---------------------------------------------------------------------------
# Single-job GPU lock
# ---------------------------------------------------------------------------
_gpu_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Background job cleanup
# ---------------------------------------------------------------------------
async def _cleanup_old_jobs():
    """Periodically delete job folders older than JOB_TTL_SECONDS."""
    while True:
        await asyncio.sleep(300)  # check every 5 min
        if not JOBS_DIR.exists():
            continue
        cutoff = time.time() - JOB_TTL_SECONDS
        for child in JOBS_DIR.iterdir():
            if child.is_dir() and child.name != ".gitkeep":
                try:
                    meta = child / "job.json"
                    if meta.exists():
                        created = json.loads(meta.read_text()).get("created", 0)
                    else:
                        created = child.stat().st_mtime
                    if created < cutoff:
                        shutil.rmtree(child, ignore_errors=True)
                except Exception:
                    pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background cleanup task on boot, cancel on shutdown."""
    task = asyncio.create_task(_cleanup_old_jobs())
    yield
    task.cancel()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SmileLoop API",
    version="0.1.0",
    description=(
        "Upload a portrait photo, pick a smile/blink preset, "
        "get an animated MP4 in seconds."
    ),
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _validate_image_bytes(header_bytes: bytes) -> str:
    """Return detected extension ('jpg'|'png') or raise 415."""
    if header_bytes[:3] == MAGIC_JPEG:
        return "jpg"
    if header_bytes[:8] == MAGIC_PNG:
        return "png"
    raise HTTPException(
        status_code=415,
        detail="Unsupported image type. Only JPEG and PNG are accepted "
               "(validated by file header magic bytes).",
    )


def _write_job_meta(job_dir: Path, **kwargs):
    """Persist lightweight job metadata as JSON."""
    meta_path = job_dir / "job.json"
    data = {"created": time.time()}
    data.update(kwargs)
    meta_path.write_text(json.dumps(data))


def _find_result_mp4(output_dir: Path) -> Optional[Path]:
    """
    Locate the clean (non-concat) MP4 that LivePortrait produces.
    LivePortrait naming:  <source_stem>--<driving_stem>.mp4
                          <source_stem>--<driving_stem>_concat.mp4
    """
    mp4s = sorted(output_dir.glob("*.mp4"))
    non_concat = [f for f in mp4s if "_concat" not in f.stem]
    if non_concat:
        return non_concat[0]
    return mp4s[0] if mp4s else None


# ---------------------------------------------------------------------------
# Startup check
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _startup_checks():
    if not INFERENCE_SCRIPT.exists():
        print(
            f"⚠  WARNING: LivePortrait inference.py not found at "
            f"{INFERENCE_SCRIPT}\n"
            f"   Set the LIVEPORTRAIT_ROOT env var to the LivePortrait repo path.",
            file=sys.stderr,
        )
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    global PRESETS
    PRESETS = _discover_presets()  # re-scan on startup / reload
    print(f"  SmileLoop API")
    print(f"  LivePortrait root : {LIVEPORTRAIT_ROOT}")
    print(f"  Presets dir       : {PRESETS_DIR}")
    print(f"  Presets found     : {list(PRESETS.keys()) or '⚠  NONE – add .mp4 files to presets/'}")
    print(f"  Jobs dir          : {JOBS_DIR}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "liveportrait_found": INFERENCE_SCRIPT.exists(),
        "presets_available": [k for k, v in PRESETS.items() if v.exists()],
    }



# --- Dual-mode inference: local or cloud (RunPod) ---
@app.post("/animate")
async def animate(
    source_image: UploadFile = File(..., description="Source portrait photo (JPEG or PNG, ≤ 10 MB)"),
    preset: str = Form(..., description="Motion preset: gentle_smile | big_smile | blink"),
    inference_mode: str = Query(None, description="local or cloud (runpod)", alias="mode")
):
    """
    Animate a portrait with a preset motion.
    If mode=cloud or INFERENCE_MODE=cloud, use RunPod. Otherwise, use local.
    Returns MP4 as StreamingResponse.
    """
    # Validate preset
    if preset not in PRESETS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown preset '{preset}'. Choose from: {', '.join(sorted(PRESETS))}",
        )

    contents = await source_image.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large ({len(contents):,} bytes). Maximum is {MAX_FILE_SIZE:,} bytes (10 MB).")
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    ext = _validate_image_bytes(contents[:16])

    # Decide inference mode
    mode = (inference_mode or os.environ.get("INFERENCE_MODE") or "local").lower()
    if mode not in ("local", "cloud"):
        raise HTTPException(status_code=400, detail="mode must be 'local' or 'cloud'")

    t0 = time_mod.time()
    if mode == "cloud":
        # --- RunPod cloud inference ---
        try:
            spec = importlib.util.find_spec("liveportrait_api.runpod_client")
            if not spec:
                raise ImportError("runpod_client.py not found")
            runpod_client = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(runpod_client)
            mp4_bytes = runpod_client.run_job(contents, preset)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"RunPod error: {e}")
        t1 = time_mod.time()
        return StreamingResponse(io.BytesIO(mp4_bytes), media_type="video/mp4", headers={"X-Inference-Mode": "cloud", "X-Inference-Time": str(t1-t0)})
    else:
        # --- Local inference (original pipeline) ---
        job_id = uuid.uuid4().hex
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / f"source.{ext}"
        output_dir  = job_dir / "output"
        output_dir.mkdir(exist_ok=True)
        source_path.write_bytes(contents)
        _write_job_meta(job_dir, job_id=job_id, preset=preset, status="queued")
        driving_path = PRESETS[preset]
        if not driving_path.exists():
            raise HTTPException(status_code=404, detail=f"Driving video for preset '{preset}' is missing on the server. Please add it to {PRESETS_DIR}.")
        if not INFERENCE_SCRIPT.exists():
            raise HTTPException(status_code=503, detail="LivePortrait inference engine is not configured. Set LIVEPORTRAIT_ROOT env var.")
        async with _gpu_lock:
            _write_job_meta(job_dir, job_id=job_id, preset=preset, status="running")
            result_path = await _run_inference(source_path, driving_path, output_dir)
        if result_path is None or not result_path.exists():
            _write_job_meta(job_dir, job_id=job_id, preset=preset, status="failed")
            raise HTTPException(status_code=500, detail="Animation failed – no output produced. Check server logs.")
        _write_job_meta(job_dir, job_id=job_id, preset=preset, status="done", result_file=result_path.name)
        t1 = time_mod.time()
        return FileResponse(
            path=str(result_path),
            media_type="video/mp4",
            filename=f"smileloop_{job_id[:8]}.mp4",
            headers={"X-Inference-Mode": "local", "X-Inference-Time": str(t1-t0)}
        )


@app.get("/download/{job_id}")
async def download(job_id: str):
    """
    Download the animated MP4 for a completed job.

    Phase 2 will add payment verification before serving the clean file.
    For now this returns the clean (un-watermarked) result directly.
    """
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found or expired.")

    meta_path = job_dir / "job.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Job metadata missing.")

    meta = json.loads(meta_path.read_text())
    if meta.get("status") != "done":
        raise HTTPException(
            status_code=409,
            detail=f"Job is not ready (status: {meta.get('status')}).",
        )

    result_path = job_dir / "output" / meta["result_file"]
    if not result_path.exists():
        raise HTTPException(status_code=410, detail="Result file has been cleaned up.")

    return FileResponse(
        path=str(result_path),
        media_type="video/mp4",
        filename=f"smileloop_{job_id[:8]}.mp4",
    )


@app.get("/job/{job_id}")
async def job_status(job_id: str):
    """Check the status of a job."""
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    meta_path = job_dir / "job.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Job metadata missing.")
    return JSONResponse(json.loads(meta_path.read_text()))


# ---------------------------------------------------------------------------
# Inference subprocess
# ---------------------------------------------------------------------------
async def _run_inference(
    source: Path, driving: Path, output_dir: Path
) -> Optional[Path]:
    """
    Shell out to LivePortrait inference.py and return the path to the
    produced MP4 (the non-concat paste-back version).
    """
    cmd = [
        sys.executable,
        str(INFERENCE_SCRIPT),
        "-s", str(source),
        "-d", str(driving),
        "-o", str(output_dir),
        "--flag_crop_driving_video",
    ]

    # Build a clean env for the subprocess:
    #  - Merge the system-level PATH so ffmpeg/ffprobe are always reachable
    #  - Force UTF-8 I/O so Rich progress bars (with emoji) don't crash
    #    on Windows cp1252 pipes.
    env = os.environ.copy()
    system_path = os.environ.get("PATH", "")
    machine_path = os.popen(
        'powershell -NoProfile -Command "[System.Environment]::GetEnvironmentVariable(\'Path\',\'Machine\')"'
    ).read().strip()
    if machine_path:
        env["PATH"] = machine_path + ";" + system_path
    env["PYTHONIOENCODING"] = "utf-8"

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(LIVEPORTRAIT_ROOT),
        env=env,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        print("=== LivePortrait inference FAILED ===", file=sys.stderr)
        print(stderr.decode(errors="replace"), file=sys.stderr)
        return None

    return _find_result_mp4(output_dir)
