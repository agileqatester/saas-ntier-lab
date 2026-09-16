"""Single tenant-id invariant for API, CLI, provisioner, lifecycle, and AWS identity."""

from __future__ import annotations

import re

from errors import ValidationError

TENANT_ID_RE = re.compile(r"^[a-z][a-z0-9]{0,15}$")
TENANT_ID_RULE = "^[a-z][a-z0-9]{0,15}$"


def validate_tenant_id(tenant_id: str | None) -> str:
    value = (tenant_id or "").strip()
    if not TENANT_ID_RE.match(value):
        raise ValidationError(f"invalid tenant id {value!r}; must match {TENANT_ID_RULE}")
    return value
