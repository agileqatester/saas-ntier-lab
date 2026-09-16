"""Error classification and exponential backoff."""

from __future__ import annotations

import pytest

from errors import (
    AWSRetryableError,
    PermanentProvisioningError,
    classify_aws_error,
    with_retry,
)

pytestmark = [pytest.mark.unit]


def test_throttling_is_retryable() -> None:
    err = classify_aws_error("Throttling", "slow down")
    assert isinstance(err, AWSRetryableError)
    assert err.retryable is True


def test_access_denied_is_permanent() -> None:
    err = classify_aws_error("AccessDenied", "nope")
    assert isinstance(err, PermanentProvisioningError)
    assert err.retryable is False


def test_retry_then_success() -> None:
    n = {"i": 0}

    def flaky() -> str:
        n["i"] += 1
        if n["i"] < 3:
            raise AWSRetryableError("throttle")
        return "ok"

    assert with_retry(flaky, attempts=5, base_delay=0.01) == "ok"
    assert n["i"] == 3


def test_retry_exhausted() -> None:
    def always() -> None:
        raise AWSRetryableError("still")

    with pytest.raises(AWSRetryableError):
        with_retry(always, attempts=2, base_delay=0.01)
