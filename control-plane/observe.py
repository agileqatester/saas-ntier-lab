"""Observe actual tenant infrastructure (K8s). Not the full isolation contract.

`matches_active()` means the *observed* workload edge looks up (ns, deploy,
replicas, Ingress, Service, NetPol, Quota, IRSA SA). That is necessary but not
sufficient for contract ACTIVE — see `validate_active_contract` in
`contract_check.py` and `tests/contracts/tenant_contract.md`.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Observed:
    namespace: bool = False
    deploy_ready: bool = False
    replicas: int = 0
    ingress: bool = False
    service: bool = False
    network_policy: bool = False
    resource_quota: bool = False
    irsa_sa: bool = False
    secret: bool | None = None
    irsa: bool | None = None

    def matches_active(self) -> bool:
        """Infrastructure looks like a live product edge — not full isolation QA."""
        return (
            self.namespace
            and self.deploy_ready
            and self.replicas >= 1
            and self.ingress
            and self.service
            and self.network_policy
            and self.resource_quota
            and self.irsa_sa
        )

    def matches_suspended(self) -> bool:
        return self.namespace and self.replicas == 0 and not self.ingress

    def matches_gone(self) -> bool:
        return not self.namespace

    def as_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


class Observer(Protocol):
    def observe(self, tenant_id: str, item: dict[str, Any]) -> Observed: ...


def _kubectl_json(args: list[str]) -> dict | None:
    proc = subprocess.run(
        ["kubectl", *args, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


class KubectlObserver:
    """Live cluster observer. Does not invent ACTIVE from namespace-only."""

    def observe(self, tenant_id: str, item: dict[str, Any]) -> Observed:
        ns = f"tenant-{tenant_id}"
        ns_obj = _kubectl_json(["get", "ns", ns])
        if not ns_obj:
            return Observed()
        deploy = _kubectl_json(["-n", ns, "get", "deploy", "test-app"])
        replicas = 0
        ready = False
        if deploy:
            spec = int((deploy.get("spec") or {}).get("replicas") or 0)
            status = deploy.get("status") or {}
            ready_n = int(status.get("readyReplicas") or 0)
            replicas = spec
            ready = spec >= 1 and ready_n >= 1
        ingress = _kubectl_json(["-n", ns, "get", "ingress", "test-app"]) is not None
        service = _kubectl_json(["-n", ns, "get", "svc", "test-app"]) is not None
        network_policy = _kubectl_json(["-n", ns, "get", "networkpolicy", "test-app"]) is not None
        resource_quota = (
            _kubectl_json(["-n", ns, "get", "resourcequota", "test-app-quota"]) is not None
        )
        sa = _kubectl_json(["-n", ns, "get", "sa", "test-app"])
        irsa_sa = bool(
            sa
            and ((sa.get("metadata") or {}).get("annotations") or {}).get(
                "eks.amazonaws.com/role-arn"
            )
        )
        return Observed(
            namespace=True,
            deploy_ready=ready,
            replicas=replicas,
            ingress=ingress,
            service=service,
            network_policy=network_policy,
            resource_quota=resource_quota,
            irsa_sa=irsa_sa,
        )
