"""Lab-only tenant authorization. Not authentication.

Callers send X-Lab-User. The app checks that name against a static map
before serving the pod's tenant. PostgreSQL must never see this header;
session tenant_id comes from the pod env (TENANT_ID) and RLS.
"""

from __future__ import annotations

import json
from typing import Any

LAB_USER_HEADER = "X-Lab-User"


def normalize_tenant_id(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v.startswith("tenant-"):
        return v[len("tenant-") :]
    return v


def load_lab_users(raw: str | None) -> dict[str, list[str]]:
    if not raw or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    users: dict[str, list[str]] = {}
    for name, tenants in data.items():
        key = str(name).strip()
        if not key:
            continue
        if isinstance(tenants, str):
            tenants = [tenants]
        if not isinstance(tenants, (list, tuple)):
            continue
        users[key] = [str(t).strip() for t in tenants if str(t).strip()]
    return users


def authorize_lab_user(
    *,
    user: str | None,
    tenant_id: str | None,
    users: dict[str, list[str]],
) -> tuple[int, dict[str, Any]] | None:
    """Return (status, body) if the request must be rejected; None if allowed."""
    name = (user or "").strip()
    if not name:
        return 401, {
            "error": "unauthorized",
            "message": "Missing X-Lab-User header",
        }
    allowed = users.get(name)
    if allowed is None:
        return 401, {
            "error": "unauthorized",
            "message": "Unknown lab user",
            "user": name,
        }
    pod_tenant = normalize_tenant_id(tenant_id)
    allowed_ids = {normalize_tenant_id(t) for t in allowed}
    if not pod_tenant or pod_tenant not in allowed_ids:
        return 403, {
            "error": "forbidden",
            "message": "User is not authorized for this tenant",
            "user": name,
            "tenant_id": tenant_id or None,
        }
    return None
