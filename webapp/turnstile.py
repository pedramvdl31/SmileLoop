# coding: utf-8
"""
SmileLoop – Cloudflare Turnstile Verification

Server-side token verification for bot protection.
Called before any GPU-expensive generation request.

Docs: https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
"""

import httpx

from webapp.config import TURNSTILE_SECRET_KEY

_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileError(Exception):
    """Raised when Turnstile verification fails."""

    def __init__(self, message: str, error_codes: list | None = None):
        super().__init__(message)
        self.error_codes = error_codes or []


async def verify_turnstile_token(
    token: str,
    remote_ip: str | None = None,
    secret_key: str | None = None,
) -> bool:
    """
    Verify a Turnstile response token with Cloudflare.

    Args:
        token: The cf-turnstile-response token from the frontend.
        remote_ip: Optional client IP for additional validation.
        secret_key: Override the configured secret (useful for tests).

    Returns:
        True if verification passed.

    Raises:
        TurnstileError: If verification fails or token is invalid/expired.
    """
    secret = secret_key or TURNSTILE_SECRET_KEY
    if not secret:
        raise TurnstileError("Turnstile secret key is not configured.")

    if not token or not token.strip():
        raise TurnstileError("Missing bot verification token.")

    payload = {
        "secret": secret,
        "response": token,
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_VERIFY_URL, data=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise TurnstileError(f"Turnstile verification request failed: {e}")

    if data.get("success"):
        return True

    error_codes = data.get("error-codes", [])
    if "timeout-or-duplicate" in error_codes:
        raise TurnstileError(
            "Bot verification expired. Please try again.",
            error_codes=error_codes,
        )

    raise TurnstileError(
        "Bot verification failed. Please try again.",
        error_codes=error_codes,
    )
