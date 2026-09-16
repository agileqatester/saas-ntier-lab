"""Lab user authorization mapping — no cluster required."""

from __future__ import annotations

import json

import pytest

from lab_auth import authorize_lab_user, load_lab_users, normalize_tenant_id

pytestmark = [pytest.mark.unit]

USERS = load_lab_users(
    json.dumps(
        {
            "alice": ["a"],
            "bob": ["b"],
            "admin": ["a", "b"],
            "user-a": ["tenant-a"],
            "user-b": ["tenant-b"],
        }
    )
)


def test_normalize_accepts_tenant_prefix() -> None:
    assert normalize_tenant_id("tenant-a") == "a"
    assert normalize_tenant_id("a") == "a"


@pytest.mark.parametrize(
    ("user", "tenant"),
    [
        ("user-a", "a"),
        ("user-a", "tenant-a"),
        ("alice", "a"),
        ("user-b", "b"),
        ("admin", "a"),
        ("admin", "b"),
    ],
)
def test_allowed_users(user: str, tenant: str) -> None:
    assert authorize_lab_user(user=user, tenant_id=tenant, users=USERS) is None


@pytest.mark.parametrize(
    ("user", "tenant"),
    [
        ("user-a", "b"),
        ("user-a", "tenant-b"),
        ("alice", "b"),
        ("user-b", "a"),
        ("bob", "a"),
    ],
)
def test_cross_tenant_is_forbidden(user: str, tenant: str) -> None:
    status, body = authorize_lab_user(user=user, tenant_id=tenant, users=USERS)
    assert status == 403
    assert body["error"] == "forbidden"


def test_missing_user_is_unauthorized() -> None:
    status, body = authorize_lab_user(user="", tenant_id="a", users=USERS)
    assert status == 401
    assert "Missing" in body["message"]


def test_unknown_user_is_unauthorized() -> None:
    status, body = authorize_lab_user(user="mallory", tenant_id="a", users=USERS)
    assert status == 401
    assert body["user"] == "mallory"


def test_header_does_not_select_tenant() -> None:
    """Admin is allowed on a, but the pod tenant is still a — not a client-chosen id."""
    assert authorize_lab_user(user="admin", tenant_id="a", users=USERS) is None
    status, body = authorize_lab_user(user="alice", tenant_id="b", users=USERS)
    assert status == 403
    assert body["tenant_id"] == "b"
