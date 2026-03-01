# coding: utf-8
"""
SmileLoop \u2013 Main Web Application

Single-page flow:
  Upload photo \u2192 enter email \u2192 Generate (Turnstile) \u2192 watermark preview
  \u2192 Stripe unlock \u2192 download full video

Endpoints:
  GET  /                                     Serve SPA
  GET  /api/health                           Health check
  GET  /api/config                           Public config
  POST /api/generate                         Image + email + turnstile \u2192 job_id
  GET  /api/status/{job_id}                  Poll job status
  POST /api/stripe/create-checkout-session   Stripe Checkout
  POST /api/stripe/webhook                   Stripe webhook
  POST /api/verify-payment/{job_id}          Verify payment
  GET  /api/preview/{job_id}                 Watermarked preview
  GET  /api/download/{job_id}                Full video (paid only)
"""

import asyncio
import re
import shutil
import tempfile
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from webapp.config import (
    APP_URL,
    DEFAULT_PROMPT,
    GROK_VIDEO_DURATION,
    GROK_VIDEO_MODE,
    GROK_VIDEO_RESOLUTION,
    JOB_TTL_HOURS,
    KIE_API_KEY,
    MAX_FILE_SIZE,
    OUTPUTS_DIR,
    PUBLIC_DIR,
    STRIPE_PRICE_CENTS,
    STRIPE_PUBLISHABLE_KEY,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    TURNSTILE_SITE_KEY,
    UPLOADS_DIR,
    VIDEO_PROVIDER,
    XAI_API_KEY,
)
from webapp.api_logger import log_webapp_request, get_recent_logs
from webapp.email_service import send_preview_ready_email
from webapp.rate_limit import check_rate_limits, record_request
from webapp.turnstile import TurnstileError, verify_turnstile_token
from webapp.watermark import create_watermarked_preview
from webapp.s3_storage import s3_enabled, upload_video, upload_image, get_video_stream, download_bytes
from webapp.database import (
    create_job,
    get_job,
    get_job_by_stripe_session,
    increment_download_count,
    init_db,
    update_job,
)


# ---------------------------------------------------------------------------
# Stripe (optional)
# ---------------------------------------------------------------------------
stripe = None
if STRIPE_SECRET_KEY:
    try:
        import stripe as _stripe
        _stripe.api_key = STRIPE_SECRET_KEY
        stripe = _stripe
    except ImportError:
        print("WARNING: stripe package not installed.")


# ---------------------------------------------------------------------------
# Image validation
# ---------------------------------------------------------------------------
def _validate_image(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
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
    while True:
        await asyncio.sleep(3600)
        cutoff = time.time() - (JOB_TTL_HOURS * 3600)
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
        # Clean old temp mp4 files from S3 downloads
        tmp_dir = Path(tempfile.gettempdir())
        for f in tmp_dir.glob("tmp*.mp4"):
            try:
                if f.stat().st_mtime < time.time() - 600:  # 10 min old
                    f.unlink(missing_ok=True)
            except Exception:
                pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(_cleanup_old_jobs())
    stripe_status = "configured" if STRIPE_SECRET_KEY else "NOT SET"
    turnstile_status = "configured" if TURNSTILE_SITE_KEY else "NOT SET"
    print()
    print("  +==========================================+")
    print("  |  SmileLoop Web Application               |")
    print("  |  Turn one photo into one moment of joy.  |")
    print("  +------------------------------------------+")
    print(f"  |  Provider  : {VIDEO_PROVIDER:<28s}|")
    print(f"  |  Stripe    : {stripe_status:<28s}|")
    print(f"  |  Price     : ${STRIPE_PRICE_CENTS / 100:.2f}{'':25s}|")
    print(f"  |  Turnstile : {turnstile_status:<28s}|")
    print("  +==========================================+")
    print()
    yield
    task.cancel()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SmileLoop",
    version="2.0.0",
    description="Turn one photo into one moment of joy.",
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
        "video_provider": VIDEO_PROVIDER,
    }


@app.get("/api/config")
async def get_config():
    """Public config for frontend."""
    return {
        "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY,
        "price_cents": STRIPE_PRICE_CENTS,
        "price_display": f"${STRIPE_PRICE_CENTS / 100:.2f}",
        "turnstile_site_key": TURNSTILE_SITE_KEY,
    }


# ---------------------------------------------------------------------------
# POST /api/generate
# ---------------------------------------------------------------------------

@app.post("/api/generate")
async def generate(
    request: Request,
    source_image: UploadFile = File(..., description="Portrait photo (JPEG/PNG, max 10 MB)"),
    email: str = Form(..., description="User email (required)"),
    cf_turnstile_token: str = Form("", description="Cloudflare Turnstile token"),
):
    """
    Accept image + email + Turnstile token.
    Verify bot check, enforce rate limits, create job, start generation.
    Returns {job_id} immediately.
    """
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")[:500]

    # -- Validate email --
    if not email or not email.strip():
        raise HTTPException(status_code=422, detail="Email is required.")
    email = _validate_email(email)

    # -- Bot verification (Turnstile) --
    try:
        await verify_turnstile_token(cf_turnstile_token, remote_ip=client_ip)
    except TurnstileError as e:
        log_webapp_request(
            event="turnstile_failed",
            method="POST",
            path="/api/generate",
            error=str(e),
            extra={"ip": client_ip},
        )
        raise HTTPException(status_code=403, detail=str(e))

    # -- Rate limiting (per-IP + per-email) --
    allowed, rate_msg = check_rate_limits(client_ip, email)
    if not allowed:
        log_webapp_request(
            event="rate_limited",
            method="POST",
            path="/api/generate",
            error=rate_msg,
            extra={"ip": client_ip, "email": email},
        )
        raise HTTPException(status_code=429, detail=rate_msg)

    # -- Read and validate image --
    contents = await source_image.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Photo is too large. Maximum size is 10 MB.")
    ext = _validate_image(contents[:16])

    # -- Create job --
    job_id = create_job(
        email=email,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    # Save original image (local + S3)
    job_dir = UPLOADS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    image_path = job_dir / f"original.{ext}"
    image_path.write_bytes(contents)

    s3_image_key = ""
    if s3_enabled():
        s3_image_key = upload_image(job_id, contents, ext) or ""
        if s3_image_key:
            # Clean up local copy since it's in S3
            try:
                image_path.unlink(missing_ok=True)
                job_dir.rmdir()
            except Exception:
                pass

    # Update DB
    update_job(job_id, input_image_path=str(image_path), status="queued", s3_image_key=s3_image_key)

    # Record rate-limit hit
    record_request(client_ip, email)

    # Log
    log_webapp_request(
        event="generate",
        job_id=job_id,
        method="POST",
        path="/api/generate",
        extra={"image_size_bytes": len(contents), "image_ext": ext},
    )

    # Start background generation
    prompt = DEFAULT_PROMPT
    asyncio.create_task(_generate_video(job_id, contents, prompt))

    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Background generation
# ---------------------------------------------------------------------------

async def _generate_video(job_id: str, image_bytes: bytes, prompt: str):
    """Run video generation in background, then watermark."""
    update_job(job_id, status="processing")
    try:
        await _run_provider(job_id, image_bytes, prompt)
    except Exception as e:
        print(f"Generation failed for job {job_id}: {e}")
        traceback.print_exc()
        update_job(job_id, status="failed", error_message=str(e)[:500])


async def _run_provider(job_id: str, image_bytes: bytes, prompt: str):
    provider = VIDEO_PROVIDER

    try:
        if provider == "kie":
            from grok_api.kie_client import kie_generate_video_async
            mp4_bytes = await kie_generate_video_async(
                image_bytes=image_bytes,
                prompt=prompt,
                duration=GROK_VIDEO_DURATION,
                resolution=GROK_VIDEO_RESOLUTION,
                mode=GROK_VIDEO_MODE,
                api_key=KIE_API_KEY or None,
                job_id=job_id,
                source="webapp",
            )
        else:
            from grok_api.grok_client import grok_generate_video_async
            mp4_bytes = await grok_generate_video_async(
                image_bytes=image_bytes,
                prompt=prompt,
                duration=GROK_VIDEO_DURATION,
                resolution=GROK_VIDEO_RESOLUTION,
                job_id=job_id,
                source="webapp",
            )
    except Exception as e:
        print(f"[{provider}] Video generation failed for job {job_id}: {e}")
        log_webapp_request(
            event="generation_failed",
            job_id=job_id,
            path="/api/generate",
            error=str(e),
            extra={"provider": provider},
        )
        update_job(job_id, status="failed", error_message=str(e)[:500])
        return

    if not mp4_bytes:
        update_job(job_id, status="failed", error_message="Empty video returned")
        return

    # Save full (unwatermarked) video — local temp for watermarking
    out_dir = OUTPUTS_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    full_path = out_dir / "full.mp4"
    full_path.write_bytes(mp4_bytes)

    # Create watermarked preview
    preview_path = out_dir / "preview.mp4"
    create_watermarked_preview(full_path, preview_path)
    preview_bytes = preview_path.read_bytes()

    # Upload to S3 if configured
    s3_full_key = None
    s3_preview_key = None
    if s3_enabled():
        s3_full_key = upload_video(job_id, mp4_bytes, video_type="full")
        s3_preview_key = upload_video(job_id, preview_bytes, video_type="preview")
        if s3_full_key and s3_preview_key:
            # Clean up local files since they're in S3 now
            try:
                full_path.unlink(missing_ok=True)
                preview_path.unlink(missing_ok=True)
                out_dir.rmdir()
            except Exception:
                pass  # Not critical if cleanup fails

    update_job(
        job_id,
        status="preview_ready",
        full_video_path=str(full_path) if not s3_full_key else "",
        preview_video_path=str(preview_path) if not s3_preview_key else "",
        s3_full_key=s3_full_key or "",
        s3_preview_key=s3_preview_key or "",
    )
    log_webapp_request(
        event="generation_complete",
        job_id=job_id,
        path="/api/generate",
        extra={
            "video_size_bytes": len(mp4_bytes),
            "duration": GROK_VIDEO_DURATION,
            "provider": provider,
        },
    )
    print(f"[{provider}] Video done for job {job_id} ({len(mp4_bytes):,} bytes)")

    # Send "preview ready" email
    job = get_job(job_id)
    if job and job.get("email"):
        try:
            send_preview_ready_email(
                to_email=job["email"],
                job_id=job_id,
            )
        except Exception as e:
            print(f"WARNING: Failed to send preview email for {job_id}: {e}")


# ---------------------------------------------------------------------------
# Status polling
# ---------------------------------------------------------------------------

@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    response = {
        "job_id": job["id"],
        "status": job["status"],
        "error": job.get("error_message"),
    }

    if job["status"] in ("preview_ready", "paid"):
        response["preview_url"] = f"/api/preview/{job_id}"

    if job["status"] == "paid":
        response["full_url"] = f"/api/download/{job_id}"

    return response


# ---------------------------------------------------------------------------
# Preview (watermarked)
# ---------------------------------------------------------------------------

@app.get("/api/preview/{job_id}")
async def get_preview(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] not in ("preview_ready", "paid"):
        raise HTTPException(status_code=409, detail="Preview not ready yet.")

    # Try S3 first — download to temp file so FileResponse handles Range requests
    s3_key = job.get("s3_preview_key")
    if s3_key:
        data = download_bytes(s3_key)
        if data:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp.write(data)
            tmp.close()
            return FileResponse(
                path=tmp.name,
                media_type="video/mp4",
                filename=f"smileloop_preview_{job_id}.mp4",
            )

    # Fall back to local file
    preview_path_str = job.get("preview_video_path", "")
    preview_path = Path(preview_path_str) if preview_path_str else None
    if not preview_path or not preview_path.is_file():
        raise HTTPException(status_code=410, detail="Preview file not found.")

    return FileResponse(
        path=str(preview_path),
        media_type="video/mp4",
        filename=f"smileloop_preview_{job_id}.mp4",
    )


# ---------------------------------------------------------------------------
# Stripe Payment
# ---------------------------------------------------------------------------

@app.post("/api/stripe/create-checkout-session")
async def create_checkout(request: Request):
    if not stripe:
        raise HTTPException(status_code=503, detail="Payments are not configured.")

    body = await request.json()
    job_id = body.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required.")

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] not in ("preview_ready",):
        if job["status"] == "paid":
            return {"already_paid": True, "download_url": f"/api/download/{job_id}"}
        raise HTTPException(status_code=409, detail="Job not ready for payment.")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": STRIPE_PRICE_CENTS,
                    "product_data": {
                        "name": "SmileLoop \u2013 Full Video",
                        "description": "Full HD animated video without watermark",
                    },
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{APP_URL}/?job_id={job_id}&payment=success",
            cancel_url=f"{APP_URL}/?job_id={job_id}&payment=cancelled",
            customer_email=job["email"],
            metadata={"job_id": job_id},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {e}")

    update_job(job_id, stripe_checkout_session_id=session.id)
    return {"checkout_url": session.url, "session_id": session.id}


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    if not stripe or not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhooks not configured.")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook: {e}")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        job_id = session.get("metadata", {}).get("job_id")
        if job_id:
            update_job(
                job_id,
                status="paid",
                stripe_payment_status="paid",
                paid_at=time.time(),
            )

    return {"received": True}


@app.post("/api/verify-payment/{job_id}")
async def verify_payment(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    if job["status"] == "paid":
        return {"paid": True, "download_url": f"/api/download/{job_id}"}

    if stripe and job.get("stripe_checkout_session_id"):
        try:
            session = stripe.checkout.Session.retrieve(job["stripe_checkout_session_id"])
            if session.payment_status == "paid":
                update_job(
                    job_id,
                    status="paid",
                    stripe_payment_status="paid",
                    paid_at=time.time(),
                )
                return {"paid": True, "download_url": f"/api/download/{job_id}"}
        except Exception:
            pass

    return {"paid": False}


# ---------------------------------------------------------------------------
# Download (full, paid only)
# ---------------------------------------------------------------------------

@app.get("/api/download/{job_id}")
async def download_full(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] != "paid":
        raise HTTPException(status_code=402, detail="Payment required to download.")

    increment_download_count(job_id)
    log_webapp_request(
        event="download",
        job_id=job_id,
        method="GET",
        path=f"/api/download/{job_id}",
    )

    # Try S3 first — download to temp file so FileResponse handles Range requests
    s3_key = job.get("s3_full_key")
    if s3_key:
        data = download_bytes(s3_key)
        if data:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp.write(data)
            tmp.close()
            return FileResponse(
                path=tmp.name,
                media_type="video/mp4",
                filename=f"smileloop_{job_id}.mp4",
            )

    # Fall back to local file
    full_path_str = job.get("full_video_path", "")
    full_path = Path(full_path_str) if full_path_str else None
    if not full_path or not full_path.is_file():
        raise HTTPException(status_code=410, detail="File not found.")

    return FileResponse(
        path=str(full_path),
        media_type="video/mp4",
        filename=f"smileloop_{job_id}.mp4",
    )


# ---------------------------------------------------------------------------
# Serve Frontend
# ---------------------------------------------------------------------------

if (PUBLIC_DIR / "css").exists():
    app.mount("/css", StaticFiles(directory=str(PUBLIC_DIR / "css")), name="css")
if (PUBLIC_DIR / "js").exists():
    app.mount("/js", StaticFiles(directory=str(PUBLIC_DIR / "js")), name="js")
if (PUBLIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(PUBLIC_DIR / "assets")), name="assets")


@app.get("/api/logs")
async def view_logs(n: int = 50):
    return {"logs": get_recent_logs(n)}


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = PUBLIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>SmileLoop</h1><p>Frontend not found.</p>", status_code=500)
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    file_path = PUBLIC_DIR / full_path
    if file_path.is_file() and file_path.exists():
        return FileResponse(str(file_path))
    index_path = PUBLIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404)
