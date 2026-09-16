"""validate_active_contract gates registry ACTIVE separately from observe."""

from __future__ import annotations

import pytest

from contract_check import validate_active_contract
from observe import Observed

pytestmark = [pytest.mark.unit]


def _ok_obs() -> Observed:
    return Observed(
        namespace=True,
        deploy_ready=True,
        replicas=1,
        ingress=True,
        service=True,
        network_policy=True,
        resource_quota=True,
        irsa_sa=True,
    )


def test_contract_ok_for_control_plane_with_identity() -> None:
    result = validate_active_contract(
        "g",
        _ok_obs(),
        {
            "owned_by": "control_plane",
            "secret_name": "secret/g",
            "irsa_role_arn": "arn:role/g",
        },
    )
    assert result.ok


def test_contract_fails_missing_netpol() -> None:
    obs = Observed(
        namespace=True,
        deploy_ready=True,
        replicas=1,
        ingress=True,
        service=True,
        network_policy=False,
        resource_quota=True,
        irsa_sa=True,
    )
    result = validate_active_contract("g", obs, {"owned_by": "opentofu"})
    assert not result.ok
    assert "network_policy" in result.reason


def test_contract_fails_missing_registry_identity() -> None:
    result = validate_active_contract(
        "g",
        _ok_obs(),
        {"owned_by": "control_plane", "secret_name": None, "irsa_role_arn": "arn:x"},
    )
    assert not result.ok
    assert "secret_name" in result.reason
