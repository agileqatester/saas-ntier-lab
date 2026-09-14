"""Smoke: fail fast if the environment is not ready for isolation tests."""

from __future__ import annotations

import pytest

from lib import kubectl
from lib.tenant import Tenant

pytestmark = [pytest.mark.smoke, pytest.mark.requires_cluster]


def test_tenant_a_namespace_exists(tenant_a: Tenant) -> None:
    assert kubectl.namespace_exists(tenant_a.namespace), f"missing ns {tenant_a.namespace}"


def test_tenant_b_namespace_exists(tenant_b: Tenant) -> None:
    assert kubectl.namespace_exists(tenant_b.namespace), f"missing ns {tenant_b.namespace}"


def test_tenant_a_workload_ready(tenant_a: Tenant) -> None:
    assert kubectl.deployment_ready(tenant_a.namespace), f"{tenant_a.namespace} deploy not Ready"


def test_tenant_b_workload_ready(tenant_b: Tenant) -> None:
    assert kubectl.deployment_ready(tenant_b.namespace), f"{tenant_b.namespace} deploy not Ready"


def test_tenant_a_is_healthy(tenant_a: Tenant) -> None:
    response = tenant_a.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body.get("status") == "healthy"


def test_tenant_b_is_healthy(tenant_b: Tenant) -> None:
    response = tenant_b.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body.get("status") == "healthy"


def test_tenant_a_db_reachable(tenant_a: Tenant) -> None:
    # App route is /db/version (legacy /db/test was removed).
    response = tenant_a.get("/db/version")
    assert response.status_code == 200, response.text
    assert response.json().get("status") == "success"


def test_tenant_b_db_reachable(tenant_b: Tenant) -> None:
    response = tenant_b.get("/db/version")
    assert response.status_code == 200, response.text
    assert response.json().get("status") == "success"
