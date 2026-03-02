# coding: utf-8
"""
SmileLoop – Configuration & Environment Variables
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env file (if present) — so the app works without run_webapp.sh
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = _PROJECT_ROOT
WEBAPP_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = PROJECT_ROOT / "public"
UPLOADS_DIR = PROJECT_ROOT / "uploads"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DB_PATH = PROJECT_ROOT / "smileloop.db"

# Ensure directories exist
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_CENTS = int(os.environ.get("STRIPE_PRICE_CENTS", "499"))  # $4.99 launch price

# ---------------------------------------------------------------------------
# Video Provider: "xai" (direct xAI SDK) or "kie" (KIE API proxy)
# ---------------------------------------------------------------------------
VIDEO_PROVIDER = os.environ.get("VIDEO_PROVIDER", "xai").lower()

# ---------------------------------------------------------------------------
# xAI / Grok (direct SDK)
# ---------------------------------------------------------------------------
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")

# ---------------------------------------------------------------------------
# KIE API (Grok proxy via kie.ai)
# ---------------------------------------------------------------------------
KIE_API_KEY = os.environ.get("KIE_API_KEY", "")

# ---------------------------------------------------------------------------
# Shared Grok video settings
# ---------------------------------------------------------------------------
GROK_VIDEO_DURATION = int(os.environ.get("GROK_VIDEO_DURATION", "6"))      # seconds (1–15)
GROK_VIDEO_RESOLUTION = os.environ.get("GROK_VIDEO_RESOLUTION", "480p")    # "480p" or "720p"
GROK_VIDEO_MODE = os.environ.get("GROK_VIDEO_MODE", "normal")             # "fun", "normal", or "spicy"

# ---------------------------------------------------------------------------
# Cloudflare Turnstile (bot protection)
# Dev/test keys that always pass: https://developers.cloudflare.com/turnstile/troubleshooting/testing/
# ---------------------------------------------------------------------------
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "1x00000000000000000000AA")
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "1x0000000000000000000000000000000AA")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
APP_URL = os.environ.get("APP_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}
JOB_TTL_HOURS = int(os.environ.get("JOB_TTL_HOURS", "168"))  # 7 days

# ---------------------------------------------------------------------------
# AWS SES (email sending)
# ---------------------------------------------------------------------------
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_SES_REGION = os.environ.get("AWS_SES_REGION", "us-east-1")
EMAIL_FROM_ADDRESS = os.environ.get("EMAIL_FROM_ADDRESS", "noreply@bloopentertainment.com")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "SmileLoop")

# ---------------------------------------------------------------------------
# AWS S3 (video & image storage)
# ---------------------------------------------------------------------------
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")

# ---------------------------------------------------------------------------
# Default prompt (no user choice — single experience)
# ---------------------------------------------------------------------------
DEFAULT_PROMPT = os.environ.get(
    "DEFAULT_PROMPT",
    "this app gently brings photos to life with subtle natural human movement, "
    "interpret the scene and continue whatever feels natural for the moment, "
    "warm realistic emotion, respectful expression change, cinematic portrait motion, "
    "seamless loop, but no spoken words.",
)

PET_PROMPT = os.environ.get(
    "PET_PROMPT",
    "this app gently brings photos to life with subtle natural human movement, "
    "interpret the scene and continue whatever feels natural for the moment, "
    "warm realistic emotion, respectful expression change, cinematic portrait motion, "
    "seamless loop, but no spoken words."
    "happy animals.",
)

