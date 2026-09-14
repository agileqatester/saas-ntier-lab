"""Database / RLS isolation — centerpiece of Tenant Isolation QA v1.

Contracts:
- Tenant sees only own rows
- Query/body cannot bypass tenant binding
- Write spoof must not create another tenant's row
"""

from __future__ import annotations

import uuid

import pytest

from lib.tenant import Tenant

pytestmark = [pytest.mark.isolation, pytest.mark.requires_cluster]


def _records(payload: dict) -> list[dict]:
    if isinstance(payload.get("records"), list):
        return payload["records"]
    if isinstance(payload, list):
        return payload
    raise AssertionError(f"unexpected /db/records shape: {payload!r}")


def test_tenant_a_can_read_own_records(tenant_a: Tenant) -> None:
    marker = f"qa-own-a-{uuid.uuid4().hex[:8]}"
    created = tenant_a.post("/db/items", json={"message": marker})
    assert created.status_code == 201, created.text
    assert created.json().get("tenant_id") == tenant_a.id

    response = tenant_a.get("/db/records", params={"limit": 50})
    assert response.status_code == 200, response.text
    records = _records(response.json())
    assert all(r.get("tenant_id") == tenant_a.id for r in records)
    assert any(r.get("message") == marker for r in records)


def test_tenant_b_can_read_own_records(tenant_b: Tenant) -> None:
    marker = f"qa-own-b-{uuid.uuid4().hex[:8]}"
    created = tenant_b.post("/db/items", json={"message": marker})
    assert created.status_code == 201, created.text
    assert created.json().get("tenant_id") == tenant_b.id

    response = tenant_b.get("/db/records", params={"limit": 50})
    assert response.status_code == 200, response.text
    records = _records(response.json())
    assert all(r.get("tenant_id") == tenant_b.id for r in records)
    assert any(r.get("message") == marker for r in records)


def test_tenant_a_cannot_read_tenant_b_records_via_query(tenant_a: Tenant, tenant_b: Tenant) -> None:
    """Security property: A must never receive B's data (status may still be 200)."""
    marker = f"qa-secret-b-{uuid.uuid4().hex[:8]}"
    created = tenant_b.post("/db/items", json={"message": marker})
    assert created.status_code == 201, created.text

    response = tenant_a.get(
        "/db/records",
        params={"tenant_id": tenant_b.id, "limit": 100},
    )
    assert response.status_code == 200, response.text
    records = _records(response.json())
    assert all(r.get("tenant_id") == tenant_a.id for r in records)
    assert all(r.get("message") != marker for r in records)


def test_tenant_a_cannot_create_tenant_b_record(tenant_a: Tenant, tenant_b: Tenant) -> None:
    """Write isolation: spoofed tenant_id in body must not land as B's row."""
    marker = f"qa-spoof-{uuid.uuid4().hex[:8]}"
    response = tenant_a.post(
        "/db/items",
        json={
            "tenant_id": tenant_b.id,
            "message": marker,
        },
    )
    # App may ignore spoofed field (201 as A) or reject (4xx). Either is fine
    # if B never sees the row and any created row is owned by A.
    assert response.status_code in (201, 400, 403), response.text
    if response.status_code == 201:
        assert response.json().get("tenant_id") == tenant_a.id

    b_records = _records(tenant_b.get("/db/records", params={"limit": 100}).json())
    assert all(r.get("message") != marker for r in b_records)
