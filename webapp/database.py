# coding: utf-8
"""
SmileLoop – SQLite Database Layer
"""

import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
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
                email TEXT NOT NULL,
                animation_type TEXT NOT NULL,
                original_image_path TEXT,
                preview_video_path TEXT,
                full_video_path TEXT,
                status TEXT NOT NULL DEFAULT 'uploaded',
                stripe_session_id TEXT,
                stripe_payment_intent TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                paid_at REAL,
                download_count INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_email ON jobs(email)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_stripe_session ON jobs(stripe_session_id)
        """)


def create_job(email: str, animation_type: str, original_image_path: str) -> str:
    """Create a new job and return its ID."""
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO jobs (id, email, animation_type, original_image_path, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'uploaded', ?, ?)""",
            (job_id, email, animation_type, original_image_path, now, now),
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
            "SELECT * FROM jobs WHERE stripe_session_id = ?", (session_id,)
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
