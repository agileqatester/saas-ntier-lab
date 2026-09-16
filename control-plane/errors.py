"""Control-plane error types and retry helper.

Transient AWS/Kubernetes failures are retryable. Validation and conflicts are not.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

AWS_RETRYABLE_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "RequestLimitExceeded",
        "TooManyRequestsException",
        "ServiceUnavailable",
        "InternalError",
        "InternalFailure",
        "RequestTimeout",
        "TransactionInProgressException",
        "SlowDown",
    }
)


class ControlPlaneError(Exception):
    retryable = False
    http_status = 500


class ValidationError(ControlPlaneError):
    http_status = 400


class ConflictError(ControlPlaneError):
    http_status = 409


class DependencyError(ControlPlaneError):
    http_status = 424


class AWSRetryableError(ControlPlaneError):
    retryable = True
    http_status = 503


class KubernetesRetryableError(ControlPlaneError):
    retryable = True
    http_status = 503


class PermanentProvisioningError(ControlPlaneError):
    http_status = 500


def classify_aws_error(code: str, message: str) -> ControlPlaneError:
    if code in AWS_RETRYABLE_CODES:
        return AWSRetryableError(f"{code}: {message}")
    return PermanentProvisioningError(f"{code}: {message}")


def with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 5,
    base_delay: float = 0.4,
    retry_on: tuple[type[BaseException], ...] = (AWSRetryableError, KubernetesRetryableError),
) -> T:
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except retry_on as exc:
            last = exc
            if i + 1 >= attempts:
                raise
            time.sleep(base_delay * (2**i))
    assert last is not None
    raise last
