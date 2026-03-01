# coding: utf-8
"""
SmileLoop – SQLite-backed Rate Limiter

Limits:
  - Per-IP:    10 requests / hour
  - Per-email: 20 requests / day

Uses the rate_limits table in smileloop.db so limits survive restarts.
"""

from typing import Optional, Tuple
from webapp.database import get_rate_count, increment_rate_count

# Configuration
IP_HOURLY_LIMIT = 10
IP_WINDOW_SECONDS = 3600       # 1 hour

EMAIL_DAILY_LIMIT = 20
EMAIL_WINDOW_SECONDS = 86400   # 24 hours


def check_rate_limits(ip: str, email: str) -> Tuple[bool, Optional[str]]:
    """
    Check both per-IP and per-email rate limits.
    Returns (allowed, error_message).
    """
    # Per-IP: 10/hour
    ip_key = f"ip:{ip}"
    ip_count = get_rate_count(ip_key, "hourly", IP_WINDOW_SECONDS)
    if ip_count >= IP_HOURLY_LIMIT:
        return False, f"Rate limit exceeded. Maximum {IP_HOURLY_LIMIT} requests per hour."

    # Per-email: 20/day
    email_key = f"email:{email.lower().strip()}"
    email_count = get_rate_count(email_key, "daily", EMAIL_WINDOW_SECONDS)
    if email_count >= EMAIL_DAILY_LIMIT:
        return False, f"Rate limit exceeded. Maximum {EMAIL_DAILY_LIMIT} requests per day for this email."

    return True, None


def record_request(ip: str, email: str) -> None:
    """Record a request for both IP and email rate counters."""
    ip_key = f"ip:{ip}"
    increment_rate_count(ip_key, "hourly")

    email_key = f"email:{email.lower().strip()}"
    increment_rate_count(email_key, "daily")
