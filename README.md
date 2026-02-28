# SmileLoop — Codebase Reference

> **"See your photo smile back at you."**
>
> SmileLoop turns still portrait photos into gentle, emotionally warm animated videos.
> Users upload a photo, pick an animation (smile, wink, laugh), see a watermarked preview,
> then pay $7.99 to download the full HD version without watermark.

---

## Quick Start

```bash
# 1. Clone & enter
cd SmileLoop

# 2. Create virtualenv
python -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements_webapp.txt

# 4. Configure environment (Stripe keys, inference mode)
cp .env.example .env
# Edit .env with your Stripe keys

# 5. Run
./run_webapp.sh
# → http://localhost:8000
```

**Without Stripe**: The app runs fine — upload, generation, and preview all work. Payment buttons will show an error until you configure Stripe keys.

**Inference**: By default uses `INFERENCE_MODE=modal` (Modal serverless GPU). Set to `local` and run `liveportrait_api/server.py` on port 8001 if you have a local GPU.

---

## Directory Structure

```
SmileLoop/
├── .env.example                 # Env var template (Stripe keys, inference mode)
├── requirements.txt             # Legacy deps (requests)
├── requirements_webapp.txt      # Webapp deps (fastapi, uvicorn, stripe, httpx)
├── run_webapp.sh                # One-command launcher
├── smileloop.db                 # SQLite database (auto-created at runtime)
│
├── webapp/                      # ── MAIN WEB APPLICATION ──
│   ├── __init__.py
│   ├── app.py                   # FastAPI app — all API routes, Stripe, static serving
│   ├── config.py                # Env vars, paths, animation presets, constraints
│   ├── database.py              # SQLite layer — jobs table CRUD
│   └── watermark.py             # ffmpeg watermark overlay for preview videos
│
├── public/                      # ── STATIC FRONTEND (SPA) ──
│   ├── index.html               # Single-page app with 6 sections
│   ├── css/style.css            # Apple-inspired minimal responsive CSS
│   ├── js/app.js                # Vanilla JS — routing, upload, polling, Stripe
│   └── assets/                  # Demo images, user uploads (runtime)
│
├── liveportrait_api/            # ── INFERENCE BACKEND ──
│   ├── server.py                # Standalone FastAPI inference server (port 8001)
│   ├── modal_client.py          # Client → Modal LivePortrait GPU function
│   ├── modal_liveportrait.py    # Modal GPU definition for LivePortrait
│   ├── modal_svd.py             # Modal GPU definition for Stable Video Diffusion
│   ├── modal_svd_client.py      # Client → Modal SVD
│   ├── modal_i2v.py             # Modal GPU definition for AnimateDiff
│   ├── modal_i2v_client.py      # Client → Modal AnimateDiff
│   ├── modal_t2v.py             # Modal GPU definition for ModelScope Text-to-Video
│   ├── modal_t2v_client.py      # Client → Modal T2V
│   ├── runpod_client.py         # Legacy RunPod serverless client
│   ├── presets/                 # Driving motion files
│   │   ├── d6_1s.pkl            # 1-second subtle motion
│   │   └── d6_10s.pkl           # 10-second extended motion
│   └── jobs/                    # Local inference job workspace
│
├── uploads/                     # Uploaded source images (per job_id)
└── outputs/                     # Generated videos: full.mp4 + preview.mp4 (per job_id)
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        BROWSER                              │
│  public/index.html + js/app.js + css/style.css              │
│  (Single-page app — vanilla JS, no framework)               │
└────────────────────────┬────────────────────────────────────┘
                         │ REST API calls
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                 webapp/app.py (port 8000)                    │
│           FastAPI — serves frontend + API                    │
│                                                              │
│  /api/upload ──► _generate_animation() async task            │
│       │              │                                       │
│       ▼              ▼                                       │
│  database.py    _run_inference(image_bytes, preset)          │
│  (SQLite)            │                                       │
│                 ┌────┴─────────┬─────────────┐              │
│                 ▼              ▼              ▼               │
│              MODAL          CLOUD          LOCAL              │
│          modal_client    runpod_client   HTTP → :8001         │
│              │              │              │                  │
│              ▼              ▼              ▼                  │
│         Modal A10G     RunPod GPU    server.py                │
│                                    (LivePortrait             │
│                                     subprocess)              │
│                                                              │
│  Result: MP4 bytes                                           │
│       │                                                      │
│       ├──► outputs/{job_id}/full.mp4                         │
│       └──► watermark.py ──► outputs/{job_id}/preview.mp4     │
│                                                              │
│  /api/create-checkout ──► Stripe Checkout Session             │
│  /api/webhook ──► Mark job as "paid"                          │
│  /api/download/{job_id} ──► Serve full.mp4 (paid only)       │
└─────────────────────────────────────────────────────────────┘
```

---

## User Flow

```
Landing Page ──[CTA]──► Upload Page ──[submit]──► Processing ──[poll]──► Preview
                                                                            │
                                                                     [Unlock $7.99]
                                                                            │
                                                                   Stripe Checkout
                                                                            │
                                                               ┌────────────┴───────────┐
                                                               ▼                        ▼
                                                          Success Page          Preview (cancelled)
                                                        [Download Video]
```

**Job status lifecycle**: `uploaded` → `processing` → `preview_ready` → `paid` (or `failed`)

---

## API Endpoints

### Webapp API (port 8000)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check, Stripe status, available animations |
| `GET` | `/api/animations` | List animation types with labels |
| `GET` | `/api/config` | Public config (Stripe publishable key, price) |
| `POST` | `/api/upload` | Upload photo + animation + email → returns `job_id` |
| `GET` | `/api/status/{job_id}` | Poll job status (client polls every 2.5s) |
| `GET` | `/api/preview/{job_id}` | Stream watermarked preview MP4 |
| `POST` | `/api/create-checkout` | Create Stripe Checkout session for a job |
| `POST` | `/api/webhook` | Stripe webhook (marks job as paid) |
| `POST` | `/api/verify-payment/{job_id}` | Verify payment after redirect |
| `GET` | `/api/download/{job_id}` | Download full HD video (requires `paid` status) |
| `GET` | `/` | Serve `index.html` |
| `GET` | `/{path}` | Static files or SPA catch-all |

### Inference API (port 8001 — standalone, optional)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health + available presets |
| `POST` | `/animate` | LivePortrait: image + preset → MP4 (local/modal/cloud) |
| `POST` | `/animate-svd` | Stable Video Diffusion: image → MP4 |
| `POST` | `/image-to-video` | AnimateDiff: image + prompt → MP4 |
| `POST` | `/generate-video` | ModelScope: text prompt → MP4 |
| `GET/POST` | `/mode` | Get/set inference mode at runtime |

---

## Database Schema

**SQLite** file at project root: `smileloop.db` (auto-created on first run, WAL mode).

### Table: `jobs`

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | TEXT PK | — | 12-char hex UUID |
| `email` | TEXT NOT NULL | — | Customer email |
| `animation_type` | TEXT NOT NULL | — | `soft_smile` / `smile_wink` / `gentle_laugh` |
| `original_image_path` | TEXT | — | Path to uploaded image |
| `preview_video_path` | TEXT | — | Path to watermarked preview MP4 |
| `full_video_path` | TEXT | — | Path to full resolution MP4 |
| `status` | TEXT NOT NULL | `'uploaded'` | `uploaded` → `processing` → `preview_ready` → `paid` / `failed` |
| `stripe_session_id` | TEXT | — | Stripe Checkout session ID |
| `stripe_payment_intent` | TEXT | — | Stripe PaymentIntent ID |
| `created_at` | REAL | — | Unix timestamp |
| `updated_at` | REAL | — | Unix timestamp |
| `paid_at` | REAL | — | Unix timestamp when payment confirmed |
| `download_count` | INTEGER | `0` | Times the full video was downloaded |

**Indexes**: `idx_jobs_email`, `idx_jobs_status`, `idx_jobs_stripe_session`

---

## Animation Presets

Defined in `webapp/config.py` → `ANIMATIONS` dict.

| User-facing ID | Label | Preset key | Driving file |
|----------------|-------|------------|--------------|
| `soft_smile` | Soft Smile | `d6_1s` | `presets/d6_1s.pkl` |
| `smile_wink` | Smile + Wink | `d6_1s` | `presets/d6_1s.pkl` |
| `gentle_laugh` | Gentle Laugh | `d6_10s` | `presets/d6_10s.pkl` |

Presets are `.pkl` files in `liveportrait_api/presets/` containing serialized driving motion data.

---

## Frontend Architecture

**Single-page app** — no framework, vanilla JS in an IIFE.

### Pages (sections in index.html)

| ID | Purpose |
|----|---------|
| `#page-landing` | Hero, "How It Works", emotional copy, CTA buttons |
| `#page-upload` | Drag-and-drop photo, animation card picker, email input |
| `#page-processing` | Spinner + "Your photo is coming to life…" |
| `#page-preview` | Autoplay watermarked video, "Unlock Full Video" button |
| `#page-success` | Download button + "Create Another" |
| `#page-error` | Error message + retry |

### Key JS functions (in `js/app.js`)

| Function | What it does |
|----------|-------------|
| `showPage(name)` | SPA router — hides all sections, shows target with fade-in |
| `handleFileSelect(file)` | Validates type/size, shows thumbnail preview |
| `validateForm()` | Checks file + animation + valid email → enables submit |
| `handleSubmit()` | POST FormData to `/api/upload`, transitions to processing |
| `startPolling()` | Polls `/api/status/{job_id}` every 2.5s |
| `handlePayment()` | POST to `/api/create-checkout`, redirects to Stripe |
| `handleStripeReturn()` | On page load, checks URL params from Stripe redirect |
| `handleDownload()` | Opens `/api/download/{job_id}` in new tab |
| `resetState()` | Clears state, resets UI for new upload |

### Design

- **Colors**: warm off-white `#FDFBF7`, dark text `#1D1D1F`, soft borders
- **Font**: Inter (Google Fonts)
- **Philosophy**: Apple product page minimalism — lots of whitespace, rounded corners, subtle shadows
- **Mobile-first**: flexbox/grid, breakpoint at 480px

---

## Inference Modes

Set via `INFERENCE_MODE` env var in `.env`.

| Mode | How it works | When to use |
|------|-------------|-------------|
| `modal` (default) | Calls Modal serverless GPU via `modal_client.py` | Production — no local GPU needed |
| `cloud` | Calls RunPod serverless via `runpod_client.py` | Legacy fallback |
| `local` | HTTP call to `liveportrait_api/server.py` on port 8001 | Development with local GPU |

### Modal GPU Functions

Each is deployed as a separate Modal app:

| Modal App | File | Model | GPU |
|-----------|------|-------|-----|
| `smileloop-liveportrait` | `modal_liveportrait.py` | LivePortrait | A10G |
| `smileloop-i2v` | `modal_i2v.py` | AnimateDiff (SD 1.5 + motion adapter) | A10G |
| `smileloop-svd` | `modal_svd.py` | Stable Video Diffusion XT | A10G |
| `smileloop-t2v` | `modal_t2v.py` | ModelScope Text-to-Video | A10G |

Deploy with: `modal deploy liveportrait_api/modal_liveportrait.py` (etc.)

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `STRIPE_SECRET_KEY` | For payments | — | Stripe secret key (`sk_test_...`) |
| `STRIPE_PUBLISHABLE_KEY` | For payments | — | Stripe publishable key (`pk_test_...`) |
| `STRIPE_WEBHOOK_SECRET` | For webhooks | — | Stripe webhook signing secret |
| `STRIPE_PRICE_CENTS` | No | `799` | Price in cents ($7.99) |
| `APP_URL` | No | `http://localhost:8000` | Base URL for Stripe redirects |
| `INFERENCE_MODE` | No | `modal` | `modal` / `cloud` / `local` |
| `RUNPOD_API_KEY` | For cloud mode | — | RunPod API key |
| `RUNPOD_ENDPOINT_ID` | For cloud mode | — | RunPod endpoint ID |

---

## File Storage

| What | Location | Lifetime |
|------|----------|----------|
| Uploaded images | `uploads/{job_id}/original.{jpg,png}` | 24 hours (auto-cleanup) |
| Full video (clean) | `outputs/{job_id}/full.mp4` | 24 hours (auto-cleanup) |
| Preview video (watermarked) | `outputs/{job_id}/preview.mp4` | 24 hours (auto-cleanup) |
| SQLite database | `smileloop.db` (project root) | Persistent |

Background cleanup runs hourly, deletes files older than 24 hours.

---

## Key Code Paths

### Upload → Preview (happy path)

1. **Frontend**: User fills form → `handleSubmit()` → `POST /api/upload` with FormData
2. **Backend** (`app.py`): Validates image + email → `create_job()` in SQLite → saves image to `uploads/{job_id}/` → `asyncio.create_task(_generate_animation(...))`
3. **Generation** (`_generate_animation`): Calls `_run_inference()` with image bytes + preset → gets MP4 bytes → saves `full.mp4` → calls `add_watermark()` → saves `preview.mp4` → updates job status to `preview_ready`
4. **Frontend**: `startPolling()` hits `/api/status/{job_id}` every 2.5s → sees `preview_ready` → sets video source → `showPage('preview')`

### Payment → Download (happy path)

1. **Frontend**: User clicks "Unlock" → `handlePayment()` → `POST /api/create-checkout`
2. **Backend**: Creates Stripe Checkout Session with `job_id` in metadata → returns `checkout_url`
3. **Frontend**: Redirects to Stripe Checkout
4. **Stripe**: User pays → webhook fires `checkout.session.completed` → backend updates job status to `paid`
5. **Frontend**: User returns to `/?job_id=xxx&payment=success` → `handleStripeReturn()` → `POST /api/verify-payment/{job_id}` → sees `paid` → `showPage('success')`
6. **Frontend**: User clicks "Download" → `GET /api/download/{job_id}` → serves `full.mp4`

---

## Development Notes

- **No login system** — jobs are tracked by `job_id` only
- **No framework** on frontend — vanilla HTML/CSS/JS, zero build step
- **SQLite** — no external DB needed, WAL mode for concurrent reads
- **Watermark**: uses `ffmpeg` CLI via subprocess; falls back to plain copy if ffmpeg is unavailable
- **Stripe**: optional — the app runs without it, payment buttons just won't work
- **CORS**: wide open (`*`) for development — restrict in production
- **Hot reload**: `uvicorn --reload` watches `webapp/` and `public/` directories
