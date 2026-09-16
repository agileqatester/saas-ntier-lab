"""Control-plane bind safety and lab API token.

This is not OIDC. The HTTP API is an operator tool. Default bind is loopback.
A non-loopback bind requires CP_API_TOKEN. Production should sit behind
OIDC (Cognito / IAM Identity Center) with RBAC: platform-admin, tenant-admin,
read-only.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class BindUnsafeError(Exception):
    """Raised when CP_HOST is not loopback and no API token is configured."""


def is_loopback_host(host: str) -> bool:
    return (host or "").strip().lower() in LOOPBACK_HOSTS


def configured_token() -> str:
    return (os.environ.get("CP_API_TOKEN") or "").strip()


def assert_bind_safety(host: str, token: str | None = None) -> None:
    presented = configured_token() if token is None else (token or "").strip()
    if is_loopback_host(host):
        return
    if presented:
        return
    raise BindUnsafeError(
        f"Refusing to bind the control-plane API on {host!r} without authentication.\n"
        "Anyone who can reach POST/DELETE /tenants can create, suspend, or delete tenants.\n"
        "  • Lab default: CP_HOST=127.0.0.1 (no token)\n"
        "  • Non-loopback: set CP_API_TOKEN and send Authorization: Bearer <token>\n"
        "Production: Admin UI/API → OIDC → control plane (not a static token)."
    )


def bearer_token(authorization: str | None) -> str:
    raw = (authorization or "").strip()
    prefix = "bearer "
    if raw.lower().startswith(prefix):
        return raw[len(prefix) :].strip()
    return ""


def authorize_http(
    *,
    path: str,
    authorization: str | None,
    token: str,
) -> tuple[int, dict[str, Any]] | None:
    """Return (status, body) to reject, or None if allowed. /health is always open."""
    if path == "/health":
        return None
    secret = (token or "").strip()
    if not secret:
        return None
    presented = bearer_token(authorization)
    if not presented or not hmac.compare_digest(presented, secret):
        return 401, {
            "error": "unauthorized",
            "message": "Authorization: Bearer token required",
        }
    return None


def secret_recovery_window_days(raw: str | None = None) -> int:
    """0 = lab ForceDeleteWithoutRecovery. 7–30 = Secrets Manager recovery window.

    Deleting the secret does not revoke a live Postgres password; the DB role does.
    """
    value = (os.environ.get("CP_SECRET_RECOVERY_DAYS") if raw is None else raw) or "0"
    try:
        days = int(str(value).strip())
    except ValueError as exc:
        raise ValueError("CP_SECRET_RECOVERY_DAYS must be an integer") from exc
    if days == 0:
        return 0
    if 7 <= days <= 30:
        return days
    raise ValueError("CP_SECRET_RECOVERY_DAYS must be 0 (lab force-delete) or 7–30")
