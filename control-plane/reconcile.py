"""Reconcile desired registry state against observed K8s/AWS.

Commands set desired_status. The reconciler makes actual match desired.
discover_active() used to mark any tenant-* namespace ACTIVE; this does not.

ACTIVE in the registry means:
  observed infrastructure ready (observe.matches_active)
  AND validate_active_contract(...) ok
Full isolation (RLS, cross-tenant, egress deny, …) stays in tests/.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from contract_check import validate_active_contract
from errors import ControlPlaneError, ValidationError
from ids import validate_tenant_id
from observe import KubectlObserver, Observed, Observer
from store import TenantStore


@dataclass(frozen=True)
class Plan:
    action: str
    reason: str


def plan_action(desired: str, observed: Observed, status: str) -> Plan:
    """Pure decision: what to run given desired vs actual. No side effects.

    Option A: lifecycle verbs stay narrow — resume only from SUSPENDED;
    FAILED/DRIFT/partial with a namespace → repair (reprovision), not resume.
    """
    if desired == "GONE":
        if observed.matches_gone():
            return Plan("purge_registry", "desired GONE and namespace absent")
        return Plan("delete", "desired GONE")
    if desired == "SUSPENDED":
        if observed.matches_suspended():
            return Plan("none", "already suspended")
        return Plan("suspend", "desired SUSPENDED but workload or Ingress still up")
    if desired == "ACTIVE":
        if observed.matches_active():
            return Plan("none", "infrastructure looks active; contract check next")
        if not observed.namespace:
            return Plan("provision", "desired ACTIVE but namespace missing")
        if status == "SUSPENDED":
            return Plan("resume", "SUSPENDED namespace present; resume workload")
        return Plan(
            "repair",
            f"namespace present but not fully ACTIVE (status={status or 'unknown'}); reprovision",
        )
    return Plan("none", f"unknown desired {desired}")


def _record_observed(store: TenantStore, tenant_id: str, observed: Observed, **fields: Any) -> dict:
    payload = {"observed_json": observed.as_json(), **fields}
    return store.upsert(tenant_id, **payload)


def reconcile_one(
    store: TenantStore,
    tofu_dir: Path,
    tenant_id: str,
    *,
    observer: Observer | None = None,
    provision_fn: Callable | None = None,
    suspend_fn: Callable | None = None,
    resume_fn: Callable | None = None,
    delete_fn: Callable | None = None,
    contract_fn: Callable | None = None,
) -> dict[str, Any]:
    tenant_id = validate_tenant_id(tenant_id)
    item = store.get(tenant_id)
    if not item:
        raise ValidationError(f"tenant {tenant_id!r} not in registry")
    observer = observer or KubectlObserver()
    observed = observer.observe(tenant_id, item)
    desired = item.get("desired_status") or "ACTIVE"
    decision = plan_action(desired, observed, item.get("status") or "")
    store.upsert(tenant_id, observed_json=observed.as_json())

    if decision.action == "none":
        if desired == "GONE":
            store.delete(tenant_id)
            return {"id": tenant_id, "status": "GONE", "reconcile": decision.reason}
        if desired == "SUSPENDED":
            return _record_observed(store, tenant_id, observed, status="SUSPENDED", error=None)
        # desired ACTIVE: infra looks ready — require contract gate before ACTIVE.
        check = (contract_fn or validate_active_contract)(tenant_id, observed, item)
        if not check.ok:
            return _record_observed(
                store,
                tenant_id,
                observed,
                status="DRIFT",
                error=check.reason,
            )
        return _record_observed(
            store,
            tenant_id,
            observed,
            status="ACTIVE",
            error=None,
        )

    if decision.action == "purge_registry":
        store.delete(tenant_id)
        return {"id": tenant_id, "status": "GONE", "reconcile": decision.reason}

    try:
        if decision.action in ("provision", "repair"):
            fn = provision_fn
            if fn is None:
                from provisioner import provision

                fn = provision
            fn(store, tofu_dir, tenant_id, tier=item.get("tier") or "standard")
        elif decision.action == "suspend":
            fn = suspend_fn
            if fn is None:
                from lifecycle import suspend_tenant

                fn = suspend_tenant
            fn(store, tenant_id)
        elif decision.action == "resume":
            fn = resume_fn
            if fn is None:
                from lifecycle import resume_tenant

                fn = resume_tenant
            fn(store, tofu_dir, tenant_id)
        elif decision.action == "delete":
            fn = delete_fn
            if fn is None:
                from lifecycle import delete_tenant

                fn = delete_tenant
            fn(store, tofu_dir, tenant_id)
            gone = store.get(tenant_id)
            if not gone:
                return {"id": tenant_id, "status": "GONE", "reconcile": decision.reason}
    except ControlPlaneError as exc:
        status = "DELETE_FAILED" if desired == "GONE" else ("DRIFT" if exc.retryable else "FAILED")
        store.upsert(
            tenant_id,
            desired_status=desired,
            status=status,
            error=str(exc),
        )
        raise

    item = store.get(tenant_id) or {"id": tenant_id, "status": "GONE"}
    # After provision/resume/repair, re-check contract before trusting ACTIVE.
    if desired == "ACTIVE" and item.get("status") == "ACTIVE":
        observed = observer.observe(tenant_id, item)
        check = (contract_fn or validate_active_contract)(tenant_id, observed, item)
        if not check.ok:
            item = _record_observed(
                store,
                tenant_id,
                observed,
                status="DRIFT",
                error=check.reason,
            )
    item["reconcile"] = decision.reason
    return item


def reconcile_all(
    store: TenantStore,
    tofu_dir: Path,
    *,
    observer: Observer | None = None,
    **fns: Any,
) -> dict[str, Any]:
    results = []
    unmanaged = list_unmanaged_namespaces(store)
    for item in store.list():
        tid = item["id"]
        try:
            results.append(reconcile_one(store, tofu_dir, tid, observer=observer, **fns))
        except ControlPlaneError as exc:
            store.upsert(
                tid,
                status="DRIFT" if not exc.retryable else item.get("status"),
                error=str(exc),
            )
            results.append({"id": tid, "status": "DRIFT", "error": str(exc), "retryable": exc.retryable})
            print(f"! reconcile {tid}: {exc}", file=sys.stderr)
    return {"tenants": results, "unmanaged_namespaces": unmanaged}


def list_unmanaged_namespaces(store: TenantStore) -> list[str]:
    """tenant-* namespaces not in the registry — report, do not auto-ACTIVE."""
    known = {f"tenant-{i['id']}" for i in store.list()}
    proc = subprocess_ns()
    return [n for n in proc if n.startswith("tenant-") and n not in known]


def subprocess_ns() -> list[str]:
    import subprocess

    try:
        raw = subprocess.run(
            ["kubectl", "get", "ns", "-o", "jsonpath={.items[*].metadata.name}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    return raw.stdout.split()
