# coding: utf-8
"""
SmileLoop – Main Web Application

Production-ready FastAPI backend that serves:
  - Static frontend (HTML/CSS/JS)
  - REST API for upload → generate → preview → pay → download flow
  - Stripe checkout integration
  - SQLite job tracking
"""

import asyncio
import io
import json
import os
import re
import shutil
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from webapp.config import (
    ALLOWED_EXTENSIONS,
    ANIMATIONS,
    APP_URL,
    INFERENCE_MODE,
    MAX_FILE_SIZE,
    OUTPUTS_DIR,
    PUBLIC_DIR,
    STRIPE_PRICE_CENTS,
    STRIPE_PUBLISHABLE_KEY,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    UPLOADS_DIR,
)
from webapp.database import (
    create_job,
    get_job,
    get_job_by_stripe_session,
    increment_download_count,
    init_db,
    update_job,
)
from webapp.watermark import add_watermark

# ---------------------------------------------------------------------------
# Stripe (optional — graceful if not configured)
# ---------------------------------------------------------------------------
stripe = None
if STRIPE_SECRET_KEY:
    try:
        import stripe as _stripe

        _stripe.api_key = STRIPE_SECRET_KEY
        stripe = _stripe
    except ImportError:
        print("WARNING: stripe package not installed. Payment will be disabled.")

# ---------------------------------------------------------------------------
# Image validation
# ---------------------------------------------------------------------------
MAGIC_JPEG = b"\xff\xd8\xff"
MAGIC_PNG = b"\x89PNG\r\n\x1a\n"


def _validate_image(data: bytes) -> str:
    """Return extension if valid image, else raise."""
    if data[:3] == MAGIC_JPEG:
        return "jpg"
    if data[:8] == MAGIC_PNG:
        return "png"
    raise HTTPException(status_code=415, detail="Only JPEG and PNG images are accepted.")


def _validate_email(email: str) -> str:
    email = email.strip().lower()
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        raise HTTPException(status_code=422, detail="Please enter a valid email address.")
    return email


# ---------------------------------------------------------------------------
# Background cleanup
# ---------------------------------------------------------------------------
async def _cleanup_old_jobs():
    """Remove job files older than 24 hours."""
    while True:
        await asyncio.sleep(3600)
        cutoff = time.time() - (24 * 3600)
        for folder in [UPLOADS_DIR, OUTPUTS_DIR]:
            if not folder.exists():
                continue
            for child in folder.iterdir():
                try:
                    if child.stat().st_mtime < cutoff:
                        if child.is_dir():
                            shutil.rmtree(child, ignore_errors=True)
                        else:
                            child.unlink(missing_ok=True)
                except Exception:
                    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(_cleanup_old_jobs())
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║  SmileLoop Web Application               ║")
    print("  ║  \"See your photo smile back at you.\"     ║")
    print("  ╠══════════════════════════════════════════╣")
    print(f"  ║  Inference : {INFERENCE_MODE:<28s}║")
    print(f"  ║  Stripe    : {'configured' if STRIPE_SECRET_KEY else 'NOT SET':28s}║")
    print(f"  ║  Price     : ${STRIPE_PRICE_CENTS/100:.2f}{' ':25s}║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    yield
    task.cancel()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SmileLoop",
    version="1.0.0",
    description="Bring your photos to life.",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "stripe_configured": bool(STRIPE_SECRET_KEY),
        "animations": list(ANIMATIONS.keys()),
    }


@app.get("/api/animations")
async def list_animations():
    """Return available animation types with labels."""
    return {
        "animations": [
            {"id": k, "label": v["label"], "description": v["description"]}
            for k, v in ANIMATIONS.items()
        ]
    }


@app.get("/api/config")
async def get_config():
    """Public config for frontend."""
    return {
        "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY,
        "price_cents": STRIPE_PRICE_CENTS,
        "price_display": f"${STRIPE_PRICE_CENTS / 100:.2f}",
    }


# ---------------------------------------------------------------------------
# Upload + Generate
# ---------------------------------------------------------------------------


@app.post("/api/upload")
async def upload_and_generate(
    photo: UploadFile = File(..., description="Portrait photo (JPEG/PNG, max 10 MB)"),
    animation: str = Form(..., description="Animation type: soft_smile | smile_wink | gentle_laugh"),
    email: str = Form(..., description="User email for delivery"),
):
    """
    Accept a photo upload, validate it, create a job, and start generation.
    Returns job_id immediately — client polls /api/status/{job_id}.
    """
    # Validate animation type
    if animation not in ANIMATIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown animation '{animation}'. Choose from: {', '.join(ANIMATIONS.keys())}",
        )

    # Validate email
    email = _validate_email(email)

    # Read and validate image
    contents = await photo.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Photo is too large. Maximum size is 10 MB.")
    ext = _validate_image(contents[:16])

    # Save original image
    job_id = create_job(email=email, animation_type=animation, original_image_path="")
    job_dir = UPLOADS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    image_path = job_dir / f"original.{ext}"
    image_path.write_bytes(contents)

    # Update DB with image path
    update_job(job_id, original_image_path=str(image_path), status="processing")

    # Start async generation
    asyncio.create_task(_generate_animation(job_id, contents, animation))

    return {"job_id": job_id, "status": "processing"}


async def _generate_animation(job_id: str, image_bytes: bytes, animation_type: str):
    """Run animation generation in background."""
    try:
        preset_key = ANIMATIONS[animation_type]["preset"]
        mp4_bytes = await _run_inference(image_bytes, preset_key)

        if not mp4_bytes:
            update_job(job_id, status="failed")
            return

        # Save full (clean) video
        out_dir = OUTPUTS_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)

        full_path = out_dir / "full.mp4"
        full_path.write_bytes(mp4_bytes)

        # Create watermarked preview
        preview_path = out_dir / "preview.mp4"
        add_watermark(full_path, preview_path)

        update_job(
            job_id,
            status="preview_ready",
            full_video_path=str(full_path),
            preview_video_path=str(preview_path),
        )

    except Exception as e:
        print(f"Generation failed for job {job_id}: {e}")
        traceback.print_exc()
        update_job(job_id, status="failed")


async def _run_inference(image_bytes: bytes, preset: str) -> Optional[bytes]:
    """Call the appropriate inference backend."""
    loop = asyncio.get_event_loop()

    if INFERENCE_MODE == "modal":
        try:
            from liveportrait_api.modal_client import run_job as modal_run_job
            from liveportrait_api.config import PRESETS_DIR  # noqa: F401

            # Resolve preset to driving video path
            presets_dir = Path(__file__).resolve().parent.parent / "liveportrait_api" / "presets"
            driving_files = {f.stem: f for f in presets_dir.glob("*.mp4") if f.exists()}
            # Also check for .pkl files
            pkl_files = {f.stem: f for f in presets_dir.glob("*.pkl") if f.exists()}

            driving_path = driving_files.get(preset) or pkl_files.get(preset)

            return await loop.run_in_executor(
                None,
                lambda: modal_run_job(image_bytes, preset, driving_video_path=driving_path),
            )
        except ImportError:
            pass
        except Exception as e:
            print(f"Modal inference error: {e}")
            traceback.print_exc()
            return None

    if INFERENCE_MODE == "cloud":
        try:
            from liveportrait_api.runpod_client import run_job as runpod_run_job

            return await loop.run_in_executor(
                None,
                lambda: runpod_run_job(image_bytes, preset),
            )
        except Exception as e:
            print(f"RunPod inference error: {e}")
            return None

    # Fallback: local mode — call the existing server's animate endpoint
    try:
        import httpx

        async with httpx.AsyncClient(timeout=300) as client:
            files = {"source_image": ("photo.jpg", image_bytes, "image/jpeg")}
            data = {"preset": preset}
            resp = await client.post(
                f"http://localhost:8001/animate?mode=local",
                files=files,
                data=data,
            )
            if resp.status_code == 200:
                return resp.content
    except Exception as e:
        print(f"Local inference error: {e}")
        return None

    return None


# ---------------------------------------------------------------------------
# Status polling
# ---------------------------------------------------------------------------


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Poll job status."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    response = {
        "job_id": job["id"],
        "status": job["status"],
        "animation_type": job["animation_type"],
    }

    if job["status"] == "preview_ready":
        response["preview_url"] = f"/api/preview/{job_id}"

    if job["status"] == "paid":
        response["download_url"] = f"/api/download/{job_id}"

    return response


# ---------------------------------------------------------------------------
# Preview (watermarked)
# ---------------------------------------------------------------------------


@app.get("/api/preview/{job_id}")
async def get_preview(job_id: str):
    """Stream the watermarked preview video."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] not in ("preview_ready", "paid"):
        raise HTTPException(status_code=409, detail="Preview not ready yet.")

    preview_path = Path(job["preview_video_path"])
    if not preview_path.exists():
        raise HTTPException(status_code=410, detail="Preview file not found.")

    return FileResponse(
        path=str(preview_path),
        media_type="video/mp4",
        filename=f"smileloop_preview_{job_id}.mp4",
    )


# ---------------------------------------------------------------------------
# Stripe Payment
# ---------------------------------------------------------------------------


@app.post("/api/create-checkout")
async def create_checkout(request: Request):
    """Create a Stripe Checkout session for a job."""
    if not stripe:
        raise HTTPException(status_code=503, detail="Payments are not configured yet.")

    body = await request.json()
    job_id = body.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required.")

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] == "paid":
        return {"already_paid": True, "download_url": f"/api/download/{job_id}"}

    animation_label = ANIMATIONS.get(job["animation_type"], {}).get("label", "Animation")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": STRIPE_PRICE_CENTS,
                        "product_data": {
                            "name": f"SmileLoop – {animation_label}",
                            "description": "Full HD animated video without watermark",
                        },
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=f"{APP_URL}/?job_id={job_id}&payment=success",
            cancel_url=f"{APP_URL}/?job_id={job_id}&payment=cancelled",
            customer_email=job["email"],
            metadata={"job_id": job_id},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")

    update_job(job_id, stripe_session_id=session.id)
    return {"checkout_url": session.url, "session_id": session.id}


@app.post("/api/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    if not stripe or not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhooks not configured.")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook: {str(e)}")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        job_id = session.get("metadata", {}).get("job_id")
        if job_id:
            update_job(
                job_id,
                status="paid",
                stripe_payment_intent=session.get("payment_intent"),
                paid_at=time.time(),
            )

    return {"received": True}


@app.post("/api/verify-payment/{job_id}")
async def verify_payment(job_id: str):
    """
    Client-side verification after Stripe redirect.
    Checks if the session was actually paid.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    if job["status"] == "paid":
        return {"paid": True, "download_url": f"/api/download/{job_id}"}

    # Check Stripe session if we have one
    if stripe and job.get("stripe_session_id"):
        try:
            session = stripe.checkout.Session.retrieve(job["stripe_session_id"])
            if session.payment_status == "paid":
                update_job(
                    job_id,
                    status="paid",
                    stripe_payment_intent=session.get("payment_intent"),
                    paid_at=time.time(),
                )
                return {"paid": True, "download_url": f"/api/download/{job_id}"}
        except Exception:
            pass

    return {"paid": False}


# ---------------------------------------------------------------------------
# Download (full version, paid only)
# ---------------------------------------------------------------------------


@app.get("/api/download/{job_id}")
async def download_full(job_id: str):
    """Download the full HD video (no watermark). Requires payment."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] != "paid":
        raise HTTPException(status_code=402, detail="Payment required to download full video.")

    full_path = Path(job["full_video_path"])
    if not full_path.exists():
        raise HTTPException(status_code=410, detail="Video file not found.")

    increment_download_count(job_id)
    return FileResponse(
        path=str(full_path),
        media_type="video/mp4",
        filename=f"smileloop_{job_id}.mp4",
    )


# ---------------------------------------------------------------------------
# Serve Frontend
# ---------------------------------------------------------------------------

# Mount static assets (CSS, JS, images)
if (PUBLIC_DIR / "css").exists():
    app.mount("/css", StaticFiles(directory=str(PUBLIC_DIR / "css")), name="css")
if (PUBLIC_DIR / "js").exists():
    app.mount("/js", StaticFiles(directory=str(PUBLIC_DIR / "js")), name="js")
if (PUBLIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(PUBLIC_DIR / "assets")), name="assets")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the main single-page application."""
    index_path = PUBLIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>SmileLoop</h1><p>Frontend not found.</p>", status_code=500)
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


# Catch-all for SPA routing (must be last)
@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    """Serve static files or fall back to index.html for SPA routing."""
    # Try to serve as static file first
    file_path = PUBLIC_DIR / full_path
    if file_path.is_file() and file_path.exists():
        return FileResponse(str(file_path))
    # Fall back to SPA
    index_path = PUBLIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404)
