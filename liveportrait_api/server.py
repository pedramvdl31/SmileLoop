# coding: utf-8
"""
SmileLoop - FastAPI backend

Upload a portrait, pick a preset motion, get an animated MP4.
Wraps KlingAIResearch/LivePortrait inference without modifying its code.

Inference modes (set via CLI --mode, INFERENCE_MODE env var, or ?mode= query):
  local  - subprocess on the same machine (needs GPU + LivePortrait)
  modal  - Modal serverless GPU (pay-per-request, scales to zero)
  cloud  - RunPod serverless (legacy)
"""

import asyncio
import io
import json
import os
import shutil
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
API_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = API_DIR.parent
PRESETS_DIR = API_DIR / "presets"
JOBS_DIR = API_DIR / "jobs"

LIVEPORTRAIT_ROOT = Path(
    os.environ.get("LIVEPORTRAIT_ROOT", str(PROJECT_ROOT / "LivePortrait"))
).resolve()
INFERENCE_SCRIPT = LIVEPORTRAIT_ROOT / "inference.py"

# ---------------------------------------------------------------------------
# Preset registry - auto-discovers every .mp4 in the presets folder.
# ---------------------------------------------------------------------------
def _discover_presets() -> dict[str, Path]:
    if not PRESETS_DIR.exists():
        return {}
    return {f.stem: f for f in sorted(PRESETS_DIR.glob("*.mp4"))}

PRESETS = _discover_presets()

# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAGIC_JPEG = b"\xff\xd8\xff"
MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
JOB_TTL_SECONDS = 60 * 60  # 1 hour

# ---------------------------------------------------------------------------
# Single-job GPU lock
# ---------------------------------------------------------------------------
_gpu_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Background job cleanup
# ---------------------------------------------------------------------------
async def _cleanup_old_jobs():
    while True:
        await asyncio.sleep(300)
        if not JOBS_DIR.exists():
            continue
        cutoff = time.time() - JOB_TTL_SECONDS
        for child in JOBS_DIR.iterdir():
            if child.is_dir() and child.name != ".gitkeep":
                try:
                    meta = child / "job.json"
                    created = (
                        json.loads(meta.read_text()).get("created", 0)
                        if meta.exists()
                        else child.stat().st_mtime
                    )
                    if created < cutoff:
                        shutil.rmtree(child, ignore_errors=True)
                except Exception:
                    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_cleanup_old_jobs())
    yield
    task.cancel()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SmileLoop API",
    version="0.2.0",
    description="Upload a portrait photo, pick a motion preset, get an animated MP4.",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_VALID_MODES = ("local", "modal", "cloud")
_runtime_mode: str = os.environ.get("INFERENCE_MODE", "local").lower()


def _get_default_mode() -> str:
    return _runtime_mode


def _validate_image_bytes(header: bytes) -> str:
    if header[:3] == MAGIC_JPEG:
        return "jpg"
    if header[:8] == MAGIC_PNG:
        return "png"
    raise HTTPException(status_code=415, detail="Only JPEG and PNG images are accepted.")


def _write_job_meta(job_dir: Path, **kwargs):
    data = {"created": time.time(), **kwargs}
    (job_dir / "job.json").write_text(json.dumps(data))


def _find_result_mp4(output_dir: Path) -> Optional[Path]:
    mp4s = sorted(output_dir.glob("*.mp4"))
    non_concat = [f for f in mp4s if "_concat" not in f.stem]
    return (non_concat or mp4s or [None])[0]


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _startup():
    if not INFERENCE_SCRIPT.exists():
        print(
            f"WARNING: LivePortrait not found at {INFERENCE_SCRIPT}\n"
            f"   Set LIVEPORTRAIT_ROOT env var to fix this.",
            file=sys.stderr,
        )
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    global PRESETS
    PRESETS = _discover_presets()
    mode = _get_default_mode()
    print()
    print(f"  +==========================================+")
    print(f"  |  SmileLoop API                           |")
    print(f"  |  Mode: {mode:<35s}|")
    print(f"  +==========================================+")
    print(f"  LivePortrait : {LIVEPORTRAIT_ROOT}")
    print(f"  Presets      : {list(PRESETS.keys()) or 'NONE'}")
    print()


# Add a global counter for sequential output naming
output_counter_file = JOBS_DIR / "output_counter.txt"
if not output_counter_file.exists():
    output_counter_file.write_text("0")

def _get_next_output_number() -> int:
    """Retrieve and increment the output counter."""
    with output_counter_file.open("r+") as f:
        current_number = int(f.read().strip())
        next_number = current_number + 1
        f.seek(0)
        f.write(str(next_number))
        f.truncate()
    return next_number


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def _refresh_presets():
    global PRESETS
    PRESETS = _discover_presets()


@app.get("/health")
async def health():
    _refresh_presets()
    return {
        "status": "ok",
        "inference_mode": _get_default_mode(),
        "liveportrait_found": INFERENCE_SCRIPT.exists(),
        "presets_available": [k for k, v in PRESETS.items() if v.exists()],
    }


@app.get("/mode")
async def get_mode():
    """Get the current default inference mode."""
    return {"mode": _get_default_mode()}


@app.post("/mode/{new_mode}")
async def set_mode(new_mode: str):
    """Change the default inference mode at runtime (no restart needed)."""
    global _runtime_mode
    new_mode = new_mode.lower()
    if new_mode not in _VALID_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{new_mode}'. Choose from: {', '.join(_VALID_MODES)}",
        )
    old = _runtime_mode
    _runtime_mode = new_mode
    print(f"  Mode changed: {old} -> {new_mode}")
    return {"mode": new_mode, "previous": old}


@app.post("/animate")
async def animate(
    source_image: UploadFile = File(..., description="Portrait photo (JPEG/PNG, max 10 MB)"),
    preset: str = Form(..., description="Motion preset name"),
    inference_mode: str = Query(None, description="local | modal | cloud", alias="mode"),
):
    """
    Animate a portrait with a preset motion.

    Mode priority: ?mode= query param > INFERENCE_MODE env var > "local"
    """
    _refresh_presets()
    if preset not in PRESETS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown preset '{preset}'. Choose from: {', '.join(sorted(PRESETS))}",
        )

    contents = await source_image.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large ({len(contents):,} B). Max 10 MB.")
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    ext = _validate_image_bytes(contents[:16])

    mode = (inference_mode or _get_default_mode()).lower()
    if mode not in _VALID_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of: {', '.join(_VALID_MODES)}")

    t0 = time.time()
    job_id = uuid.uuid4().hex[:8]

    # ------------------------------------------------------------------
    # Modal serverless GPU
    # ------------------------------------------------------------------
    if mode == "modal":
        try:
            from liveportrait_api.modal_client import ModalError, run_job as modal_run_job
            mp4_bytes = modal_run_job(contents, preset, driving_video_path=PRESETS.get(preset))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Modal error: {e}")
        output_number = _get_next_output_number()
        filename = f"output_{output_number}.mp4"
        elapsed_time = f"{time.time()-t0:.2f}s"
        return StreamingResponse(
            io.BytesIO(mp4_bytes),
            media_type="video/mp4",
            headers={
                "X-Inference-Mode": "modal",
                "X-Inference-Time": elapsed_time,
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    # ------------------------------------------------------------------
    # RunPod cloud (legacy)
    # ------------------------------------------------------------------
    if mode == "cloud":
        try:
            from liveportrait_api.runpod_client import RunPodError, run_job as runpod_run_job
            mp4_bytes = runpod_run_job(contents, preset)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"RunPod error: {e}")
        output_number = _get_next_output_number()
        filename = f"output_{output_number}.mp4"
        elapsed_time = f"{time.time()-t0:.2f}s"
        return StreamingResponse(
            io.BytesIO(mp4_bytes),
            media_type="video/mp4",
            headers={
                "X-Inference-Mode": "cloud",
                "X-Inference-Time": elapsed_time,
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    # ------------------------------------------------------------------
    # Local inference (GPU subprocess)
    # ------------------------------------------------------------------
    local_job_id = uuid.uuid4().hex
    job_dir = JOBS_DIR / local_job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    source_path = job_dir / f"source.{ext}"
    output_dir = job_dir / "output"
    output_dir.mkdir(exist_ok=True)
    source_path.write_bytes(contents)
    _write_job_meta(job_dir, job_id=local_job_id, preset=preset, status="queued")

    driving_path = PRESETS[preset]
    if not driving_path.exists():
        raise HTTPException(status_code=404, detail=f"Driving video for preset '{preset}' missing.")
    if not INFERENCE_SCRIPT.exists():
        raise HTTPException(status_code=503, detail="LivePortrait not configured. Set LIVEPORTRAIT_ROOT.")

    async with _gpu_lock:
        _write_job_meta(job_dir, job_id=local_job_id, preset=preset, status="running")
        result_path = await _run_inference(source_path, driving_path, output_dir)

    if not result_path or not result_path.exists():
        _write_job_meta(job_dir, job_id=local_job_id, preset=preset, status="failed")
        raise HTTPException(status_code=500, detail="Animation failed - no output produced.")

    _write_job_meta(job_dir, job_id=local_job_id, preset=preset, status="done", result_file=result_path.name)
    output_number = _get_next_output_number()
    filename = f"output_{output_number}.mp4"
    elapsed_time = f"{time.time()-t0:.2f}s"
    return FileResponse(
        path=str(result_path),
        media_type="video/mp4",
        filename=filename,
        headers={"X-Inference-Mode": "local", "X-Inference-Time": elapsed_time},
    )


# ---------------------------------------------------------------------------
# SVD (Stable Video Diffusion) – image-to-video, no driving video needed
# ---------------------------------------------------------------------------
@app.post("/animate-svd")
async def animate_svd(
    source_image: UploadFile = File(..., description="Portrait or any image (JPEG/PNG, max 10 MB)"),
    num_frames: int = Form(25, description="Number of frames to generate (default 25)"),
    num_inference_steps: int = Form(50, description="Diffusion steps — more = better quality (default 50)"),
    fps: int = Form(7, description="Output video FPS (default 7 → ~3.5s clip)"),
    motion_bucket_id: int = Form(100, description="Motion amount 1-255 (default 100 = moderate, reduces camera shake)"),
    noise_aug_strength: float = Form(0.04, description="Augmentation level (default 0.04 = low, anchors face identity)"),
    min_guidance_scale: float = Form(1.0, description="CFG guidance on first frame (default 1.0)"),
    max_guidance_scale: float = Form(3.5, description="CFG guidance on last frame (default 3.5 — lower prevents color ringing)"),
    seed: int = Form(12345, description="RNG seed for reproducibility (default 12345)"),
    letterbox: bool = Form(False, description="If true, pad with blurred background instead of cropping"),
):
    """
    Animate any image using Stable Video Diffusion (SVD-XT).

    No driving video needed — SVD generates natural motion from the image itself.
    Runs on Modal serverless GPU (A10G). Pipeline stays loaded between calls.
    """
    contents = await source_image.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large ({len(contents):,} B). Max 10 MB.")
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    _validate_image_bytes(contents[:16])

    t0 = time.time()

    try:
        from liveportrait_api.modal_svd_client import SVDError, run_job as svd_run_job
        mp4_bytes = svd_run_job(
            contents,
            num_frames=num_frames,
            num_inference_steps=num_inference_steps,
            fps=fps,
            motion_bucket_id=motion_bucket_id,
            noise_aug_strength=noise_aug_strength,
            min_guidance_scale=min_guidance_scale,
            max_guidance_scale=max_guidance_scale,
            seed=seed,
            letterbox=letterbox,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SVD error: {e}")

    output_number = _get_next_output_number()
    filename = f"output_{output_number}.mp4"
    elapsed_time = f"{time.time()-t0:.2f}s"
    return StreamingResponse(
        io.BytesIO(mp4_bytes),
        media_type="video/mp4",
        headers={
            "X-Inference-Mode": "svd",
            "X-Inference-Time": elapsed_time,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@app.get("/download/{job_id}")
async def download(job_id: str):
    """Download the animated MP4 for a completed local job."""
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    meta_path = job_dir / "job.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Job metadata missing.")
    meta = json.loads(meta_path.read_text())
    if meta.get("status") != "done":
        raise HTTPException(status_code=409, detail=f"Job not ready (status: {meta.get('status')}).")
    result_path = job_dir / "output" / meta["result_file"]
    if not result_path.exists():
        raise HTTPException(status_code=410, detail="Result file has been cleaned up.")
    return FileResponse(path=str(result_path), media_type="video/mp4", filename=f"smileloop_{job_id[:8]}.mp4")


@app.get("/job/{job_id}")
async def job_status(job_id: str):
    """Check the status of a local job."""
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    meta_path = job_dir / "job.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Job metadata missing.")
    return JSONResponse(json.loads(meta_path.read_text()))


# ---------------------------------------------------------------------------
# Inference subprocess (local mode)
# ---------------------------------------------------------------------------
async def _run_inference(source: Path, driving: Path, output_dir: Path) -> Optional[Path]:
    cmd = [
        sys.executable,
        str(INFERENCE_SCRIPT),
        "-s", str(source),
        "-d", str(driving),
        "-o", str(output_dir),
        "--flag_crop_driving_video",
    ]

    env = os.environ.copy()
    if sys.platform == "win32":
        machine_path = os.popen(
            'powershell -NoProfile -Command '
            '"[System.Environment]::GetEnvironmentVariable(\'Path\',\'Machine\')"'
        ).read().strip()
        if machine_path:
            env["PATH"] = machine_path + ";" + env.get("PATH", "")
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
        print("=== LivePortrait FAILED ===", file=sys.stderr)
        print(stderr.decode(errors="replace"), file=sys.stderr)
        return None

    return _find_result_mp4(output_dir)
