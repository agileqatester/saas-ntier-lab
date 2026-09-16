"""Control-plane bind safety and delete-policy helpers."""

from __future__ import annotations

import pytest

from safety import (
    BindUnsafeError,
    assert_bind_safety,
    authorize_http,
    is_loopback_host,
    secret_recovery_window_days,
)

pytestmark = [pytest.mark.unit]


def test_loopback_hosts() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("10.0.0.5")


def test_non_loopback_without_token_is_refused() -> None:
    with pytest.raises(BindUnsafeError):
        assert_bind_safety("0.0.0.0", token="")


def test_non_loopback_with_token_is_allowed() -> None:
    assert_bind_safety("0.0.0.0", token="lab-token")


def test_loopback_without_token_is_allowed() -> None:
    assert_bind_safety("127.0.0.1", token="")


def test_health_is_open_even_with_token() -> None:
    assert authorize_http(path="/health", authorization=None, token="secret") is None


def test_tenants_without_token_config_allowed() -> None:
    assert authorize_http(path="/tenants", authorization=None, token="") is None


def test_tenants_require_bearer_when_token_configured() -> None:
    status, body = authorize_http(path="/tenants", authorization=None, token="secret")
    assert status == 401
    assert body["error"] == "unauthorized"


def test_tenants_accept_matching_bearer() -> None:
    assert (
        authorize_http(
            path="/tenants",
            authorization="Bearer secret",
            token="secret",
        )
        is None
    )


def test_tenants_reject_wrong_bearer() -> None:
    status, _body = authorize_http(
        path="/tenants",
        authorization="Bearer other",
        token="secret",
    )
    assert status == 401


def test_secret_recovery_lab_default() -> None:
    assert secret_recovery_window_days("0") == 0
    assert secret_recovery_window_days("7") == 7
    assert secret_recovery_window_days("30") == 30
    with pytest.raises(ValueError):
        secret_recovery_window_days("3")
