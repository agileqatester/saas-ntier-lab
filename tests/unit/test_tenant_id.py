"""Shared tenant-id validation."""

from __future__ import annotations

import pytest

from errors import ValidationError
from ids import validate_tenant_id

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("value", ["a", "g", "tenant1", "abcdefghijklmnop"])
def test_valid_ids(value: str) -> None:
    assert validate_tenant_id(value) == value


@pytest.mark.parametrize("value", ["", "A", "1a", "has_underscore", "a" * 17, "tenant-a"])
def test_invalid_ids(value: str) -> None:
    with pytest.raises(ValidationError):
        validate_tenant_id(value)
