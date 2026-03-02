# coding: utf-8
"""
SmileLoop – SQLite Database Layer

Tables:
  - jobs: video generation jobs
  - rate_limits: per-key request counters for rate limiting
"""

import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Optional

from webapp.config import DB_PATH


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                email TEXT NOT NULL,
                ip_address TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                input_image_path TEXT,
                preview_video_path TEXT,
                full_video_path TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                stripe_checkout_session_id TEXT,
                stripe_payment_status TEXT DEFAULT '',
                error_message TEXT DEFAULT '',
                updated_at REAL NOT NULL,
                paid_at REAL,
                download_count INTEGER DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                key TEXT NOT NULL,
                window TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                first_request_at REAL NOT NULL,
                PRIMARY KEY (key, window)
            )
        """)

        # ── Migrate existing jobs table if needed ──
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        new_cols = {
            "ip_address": "ALTER TABLE jobs ADD COLUMN ip_address TEXT DEFAULT ''",
            "user_agent": "ALTER TABLE jobs ADD COLUMN user_agent TEXT DEFAULT ''",
            "input_image_path": "ALTER TABLE jobs ADD COLUMN input_image_path TEXT",
            "error_message": "ALTER TABLE jobs ADD COLUMN error_message TEXT DEFAULT ''",
            "stripe_checkout_session_id": "ALTER TABLE jobs ADD COLUMN stripe_checkout_session_id TEXT",
            "stripe_payment_status": "ALTER TABLE jobs ADD COLUMN stripe_payment_status TEXT DEFAULT ''",
            "s3_full_key": "ALTER TABLE jobs ADD COLUMN s3_full_key TEXT",
            "s3_preview_key": "ALTER TABLE jobs ADD COLUMN s3_preview_key TEXT",
            "s3_image_key": "ALTER TABLE jobs ADD COLUMN s3_image_key TEXT",
            "pipeline": "ALTER TABLE jobs ADD COLUMN pipeline TEXT DEFAULT 'standard'",
            "progress_step": "ALTER TABLE jobs ADD COLUMN progress_step TEXT DEFAULT ''",
        }
        for col, sql in new_cols.items():
            if col not in existing_cols:
                try:
                    conn.execute(sql)
                    print(f"  DB migration: added '{col}' column")
                except Exception:
                    pass

        # Indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_email ON jobs(email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_stripe ON jobs(stripe_checkout_session_id)")


# ---------------------------------------------------------------------------
# Job CRUD
# ---------------------------------------------------------------------------

def create_job(email: str, ip_address: str = "", user_agent: str = "") -> str:
    """Create a new job and return its ID."""
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO jobs
               (id, created_at, email, ip_address, user_agent, status, updated_at)
               VALUES (?, ?, ?, ?, ?, 'queued', ?)""",
            (job_id, now, email, ip_address, user_agent, now),
        )
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    """Get a job by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row:
            return dict(row)
    return None


def update_job(job_id: str, **kwargs):
    """Update job fields."""
    kwargs["updated_at"] = time.time()
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [job_id]
    with get_db() as conn:
        conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)


def get_job_by_stripe_session(session_id: str) -> Optional[dict]:
    """Look up a job by Stripe checkout session ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE stripe_checkout_session_id = ?", (session_id,)
        ).fetchone()
        if row:
            return dict(row)
    return None


def increment_download_count(job_id: str):
    """Bump download counter."""
    with get_db() as conn:
        conn.execute(
            "UPDATE jobs SET download_count = download_count + 1, updated_at = ? WHERE id = ?",
            (time.time(), job_id),
        )


# ---------------------------------------------------------------------------
# Rate Limiting helpers
# ---------------------------------------------------------------------------

def get_rate_count(key: str, window: str, window_seconds: int) -> int:
    """
    Get the current request count for a rate-limit key within its window.
    Automatically resets if the window has expired.
    """
    now = time.time()
    with get_db() as conn:
        row = conn.execute(
            "SELECT count, first_request_at FROM rate_limits WHERE key = ? AND window = ?",
            (key, window),
        ).fetchone()

        if row is None:
            return 0

        # Check if window has expired
        if now - row["first_request_at"] > window_seconds:
            conn.execute(
                "DELETE FROM rate_limits WHERE key = ? AND window = ?",
                (key, window),
            )
            return 0

        return row["count"]


def increment_rate_count(key: str, window: str) -> None:
    """Increment the rate-limit counter for a key. Creates the row if needed."""
    now = time.time()
    with get_db() as conn:
        row = conn.execute(
            "SELECT count, first_request_at FROM rate_limits WHERE key = ? AND window = ?",
            (key, window),
        ).fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO rate_limits (key, window, count, first_request_at) VALUES (?, ?, 1, ?)",
                (key, window, now),
            )
        else:
            conn.execute(
                "UPDATE rate_limits SET count = count + 1 WHERE key = ? AND window = ?",
                (key, window),
            )
