"""Postgres role teardown must revoke before DROP, and fail closed in lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from pg_admin import _DROP_SCRIPT

pytestmark = [pytest.mark.unit]

LIFECYCLE = Path(__file__).resolve().parents[2] / "control-plane" / "lifecycle.py"


def test_drop_script_disables_role_before_drop() -> None:
    assert "ALTER ROLE {} NOLOGIN" in _DROP_SCRIPT
    assert "PASSWORD" in _DROP_SCRIPT
    assert "DROP ROLE" in _DROP_SCRIPT


def test_delete_does_not_swallow_db_revoke_failure() -> None:
    src = LIFECYCLE.read_text()
    assert "drop postgres role warning" not in src
    body = src.split("def delete_tenant", 1)[1]
    assert "DELETE_FAILED" in body
    access = body.index("_disable_application_access")
    revoke = body.index("_revoke_postgres_role")
    k8s = body.index("_delete_kubernetes")
    iam = body.index("delete_tenant_irsa")
    secret = body.index("delete_tenant_secret")
    assert access < revoke < k8s < iam < secret
