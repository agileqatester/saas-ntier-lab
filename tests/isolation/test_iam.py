"""IAM / IRSA isolation — allow own secret, deny peer secret (from inside the pod)."""

from __future__ import annotations

import pytest

from lib.tenant import Tenant

pytestmark = [pytest.mark.isolation, pytest.mark.requires_cluster]


def test_tenant_a_can_read_own_secret(tenant_a: Tenant) -> None:
    assert tenant_a.secret_name
    result = tenant_a.get_secret(tenant_a.secret_name)
    assert result.success, result.stderr or result.stdout
    assert "ALLOW" in result.stdout


def test_tenant_b_can_read_own_secret(tenant_b: Tenant) -> None:
    assert tenant_b.secret_name
    result = tenant_b.get_secret(tenant_b.secret_name)
    assert result.success, result.stderr or result.stdout
    assert "ALLOW" in result.stdout


def test_tenant_a_cannot_read_tenant_b_secret(tenant_a: Tenant, tenant_b: Tenant) -> None:
    assert tenant_b.secret_name
    result = tenant_a.get_secret(tenant_b.secret_name)
    assert result.failed, f"expected deny, got: {result.stdout}"
    assert "DENY" in result.stdout or "AccessDenied" in (result.stdout + result.stderr)


def test_tenant_b_cannot_read_tenant_a_secret(tenant_a: Tenant, tenant_b: Tenant) -> None:
    assert tenant_a.secret_name
    result = tenant_b.get_secret(tenant_a.secret_name)
    assert result.failed, f"expected deny, got: {result.stdout}"
    assert "DENY" in result.stdout or "AccessDenied" in (result.stdout + result.stderr)
