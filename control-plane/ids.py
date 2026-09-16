"""Single tenant-id invariant for API, CLI, provisioner, lifecycle, and AWS identity."""

from __future__ import annotations

import re

from errors import ValidationError

TENANT_ID_RE = re.compile(r"^[a-z][a-z0-9]{0,15}\Z")
TENANT_ID_RULE = "^[a-z][a-z0-9]{0,15}$"


def validate_tenant_id(tenant_id: str | None) -> str:
    # No strip: leading/trailing whitespace or newlines must fail closed
    # (DELETE /tenants/... feeds Job manifests under migrator IRSA).
    value = tenant_id or ""
    if not TENANT_ID_RE.match(value):
        raise ValidationError(f"invalid tenant id {value!r}; must match {TENANT_ID_RULE}")
    return value
