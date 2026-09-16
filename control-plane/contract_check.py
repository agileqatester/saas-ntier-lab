"""Cheap ACTIVE gate for the reconciler — not the full isolation pytest suite.

Observed infrastructure (`observe.matches_active`) checks that isolation
*objects* are present. This module checks registry + observed fields that
the control plane can assert without running live RLS/IAM/NetPol probes.

Full contract proof remains `tests/` (see tenant_contract.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from observe import Observed


@dataclass(frozen=True)
class ContractResult:
    ok: bool
    reason: str


def validate_active_contract(
    tenant_id: str,
    observed: Observed,
    item: dict[str, Any],
) -> ContractResult:
    """Gate registry ACTIVE after infrastructure looks up.

    Fail closed: missing IRSA annotation, NetPol, Quota, Service, or registry
    identity pointers → not ACTIVE (DRIFT), even if pods are Ready.
    """
    if not observed.matches_active():
        missing = []
        if not observed.namespace:
            missing.append("namespace")
        if not observed.deploy_ready or observed.replicas < 1:
            missing.append("ready_workload")
        if not observed.ingress:
            missing.append("ingress")
        if not observed.service:
            missing.append("service")
        if not observed.network_policy:
            missing.append("network_policy")
        if not observed.resource_quota:
            missing.append("resource_quota")
        if not observed.irsa_sa:
            missing.append("irsa_serviceaccount")
        return ContractResult(False, f"infra incomplete: {','.join(missing) or 'unknown'}")

    if item.get("owned_by") == "control_plane":
        if not item.get("secret_name"):
            return ContractResult(False, "registry missing secret_name")
        if not item.get("irsa_role_arn"):
            return ContractResult(False, "registry missing irsa_role_arn")

    return ContractResult(
        True,
        "infra + registry identity present; full isolation proof is tests/",
    )
