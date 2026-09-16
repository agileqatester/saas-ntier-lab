"""SQLite registry: transactions and optimistic concurrency."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import ConflictError, ValidationError
from store import TenantStore

pytestmark = [pytest.mark.unit]


def test_upsert_get_delete(tmp_path: Path) -> None:
    store = TenantStore(tmp_path / "tenants.db")
    store.upsert("a", status="ACTIVE", desired_status="ACTIVE", tier="standard")
    item = store.get("a")
    assert item is not None
    assert item["status"] == "ACTIVE"
    assert item["version"] == 1
    store.upsert("a", status="SUSPENDED")
    assert store.get("a")["version"] == 2
    assert store.delete("a") is True
    assert store.get("a") is None


def test_version_conflict(tmp_path: Path) -> None:
    store = TenantStore(tmp_path / "tenants.db")
    store.upsert("b", status="ACTIVE", desired_status="ACTIVE")
    with pytest.raises(ConflictError):
        store.upsert("b", expected_version=99, status="SUSPENDED")
    store.upsert("b", expected_version=1, status="SUSPENDED")
    assert store.get("b")["status"] == "SUSPENDED"


def test_rejects_bad_id(tmp_path: Path) -> None:
    store = TenantStore(tmp_path / "tenants.db")
    with pytest.raises(ValidationError):
        store.upsert("NOPE", status="ACTIVE")


def test_imports_legacy_json(tmp_path: Path) -> None:
    legacy = tmp_path / "tenants.json"
    legacy.write_text(
        json.dumps({"tenants": {"c": {"status": "ACTIVE", "owned_by": "control_plane"}}})
    )
    store = TenantStore(tmp_path / "tenants.db")
    item = store.get("c")
    assert item is not None
    assert item["desired_status"] == "ACTIVE"
    assert item["owned_by"] == "control_plane"
