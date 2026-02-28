# coding: utf-8
"""
SmileLoop – Configuration & Environment Variables
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
STRIPE_PRICE_CENTS = int(os.environ.get("STRIPE_PRICE_CENTS", "799"))  # $7.99

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
APP_URL = os.environ.get("APP_URL", "http://localhost:8000")
INFERENCE_MODE = os.environ.get("INFERENCE_MODE", "modal").lower()

# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}
JOB_TTL_HOURS = 24

# ---------------------------------------------------------------------------
# Animation presets for the webapp
# ---------------------------------------------------------------------------
ANIMATIONS = {
    "soft_smile": {
        "label": "Soft Smile",
        "description": "A gentle, warm smile",
        "preset": "d6_1s",  # maps to existing preset
    },
    "smile_wink": {
        "label": "Smile + Wink",
        "description": "A smile with a playful wink",
        "preset": "d6_1s",  # can be updated when new presets arrive
    },
    "gentle_laugh": {
        "label": "Gentle Laugh",
        "description": "A soft, natural laugh",
        "preset": "d6_10s",  # maps to longer preset
    },
}
