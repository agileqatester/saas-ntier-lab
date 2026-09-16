"""Tenant authorization (lab user header) — application boundary, not Postgres.

Authentication is out of scope. X-Lab-User is a simulated caller. The pod still
binds PostgreSQL session tenant_id from TENANT_ID (Helm), never from the header.
"""

from __future__ import annotations

import uuid

import pytest

from lib.tenant import Tenant

pytestmark = [pytest.mark.isolation, pytest.mark.requires_cluster]


def test_health_does_not_require_lab_user(tenant_a: Tenant) -> None:
    response = tenant_a.get("/health", user="")
    assert response.status_code == 200, response.text
    assert response.json().get("status") == "healthy"


def test_user_a_can_access_tenant_a(tenant_a: Tenant) -> None:
    response = tenant_a.request("GET", "/", user="user-a")
    assert response.status_code == 200, response.text
    assert response.json().get("tenant_id") == tenant_a.id


def test_user_b_can_access_tenant_b(tenant_b: Tenant) -> None:
    response = tenant_b.request("GET", "/", user="user-b")
    assert response.status_code == 200, response.text
    assert response.json().get("tenant_id") == tenant_b.id


def test_user_a_cannot_access_tenant_b(tenant_b: Tenant) -> None:
    response = tenant_b.request("GET", "/", user="user-a")
    assert response.status_code == 403, response.text
    assert response.json().get("error") == "forbidden"


def test_user_b_cannot_access_tenant_a(tenant_a: Tenant) -> None:
    response = tenant_a.request("GET", "/", user="user-b")
    assert response.status_code == 403, response.text
    assert response.json().get("error") == "forbidden"


def test_admin_can_access_both_tenants(tenant_a: Tenant, tenant_b: Tenant) -> None:
    a = tenant_a.request("GET", "/", user="admin")
    b = tenant_b.request("GET", "/", user="admin")
    assert a.status_code == 200, a.text
    assert b.status_code == 200, b.text
    assert a.json().get("tenant_id") == tenant_a.id
    assert b.json().get("tenant_id") == tenant_b.id


def test_missing_lab_user_is_rejected(tenant_a: Tenant) -> None:
    response = tenant_a.request("GET", "/", user="")
    assert response.status_code == 401, response.text
    assert response.json().get("error") == "unauthorized"


def test_unknown_lab_user_is_rejected(tenant_a: Tenant) -> None:
    response = tenant_a.request("GET", "/", user="mallory")
    assert response.status_code == 401, response.text
    assert response.json().get("error") == "unauthorized"


def test_lab_user_header_is_not_trusted_by_postgres(tenant_a: Tenant, tenant_b: Tenant) -> None:
    """Admin on tenant-a still writes/reads as tenant a. Header is not a DB tenant switch."""
    marker = f"qa-authz-spoof-{uuid.uuid4().hex[:8]}"
    created = tenant_a.post(
        "/db/items",
        user="admin",
        json={"tenant_id": tenant_b.id, "message": marker},
    )
    assert created.status_code == 201, created.text
    assert created.json().get("tenant_id") == tenant_a.id

    version = tenant_a.get("/db/version", user="admin")
    assert version.status_code == 200, version.text
    assert version.json().get("app.tenant_id") == tenant_a.id

    b_records = tenant_b.get("/db/records", user="user-b", params={"limit": 100}).json()
    messages = [r.get("message") for r in b_records.get("records", [])]
    assert marker not in messages
