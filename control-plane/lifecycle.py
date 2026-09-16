"""Tenant lifecycle: suspend / resume / delete (no env recreate)."""

from __future__ import annotations

import subprocess
import sys
import time
import traceback
from pathlib import Path

from errors import KubernetesRetryableError, PermanentProvisioningError
from ids import validate_tenant_id
from aws_identity import delete_tenant_irsa, delete_tenant_secret, merge_identity_maps
from onboard_bridge import OnboardError, node_ip, onboard, tofu_outputs, wait_ingress_hostname, write_alb_url
from store import TenantStore


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), file=sys.stderr)
    try:
        subprocess.check_call(cmd)
    except subprocess.TimeoutExpired as exc:
        raise KubernetesRetryableError(str(exc)) from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        msg = f"{' '.join(cmd)} exited {exc.returncode} {err}".strip()
        if "timeout" in msg.lower() or exc.returncode in (124, 137):
            raise KubernetesRetryableError(msg) from exc
        raise PermanentProvisioningError(msg) from exc


def _run_ok(cmd: list[str]) -> bool:
    print("+", " ".join(cmd), file=sys.stderr)
    return subprocess.call(cmd) == 0


def _ns(tenant_id: str) -> str:
    return f"tenant-{tenant_id}"


def _cp_identities(store: TenantStore) -> dict:
    out = {}
    for item in store.list():
        tid = item.get("id")
        if (
            tid
            and item.get("owned_by") == "control_plane"
            and item.get("secret_name")
            and item.get("irsa_role_arn")
        ):
            out[tid] = {
                "secret_name": item["secret_name"],
                "irsa_role_arn": item["irsa_role_arn"],
                "owned_by": "control_plane",
            }
    return out


def suspend_tenant(store: TenantStore, tenant_id: str) -> dict:
    tenant_id = validate_tenant_id(tenant_id)
    item = store.get(tenant_id)
    if not item:
        raise OnboardError(f"tenant {tenant_id!r} not found")
    status = item.get("status")
    if status == "SUSPENDED":
        return item
    if status not in ("ACTIVE", "FAILED", "DRIFT"):
        raise OnboardError(f"cannot suspend from status {status}")

    ns = _ns(tenant_id)
    _run(["kubectl", "-n", ns, "scale", "deploy/test-app", "--replicas=0"])
    _run_ok(["kubectl", "-n", ns, "delete", "ingress", "test-app", "--ignore-not-found"])
    return store.upsert(tenant_id, desired_status="SUSPENDED", status="SUSPENDED", error=None)


def resume_tenant(store: TenantStore, tofu_dir: Path, tenant_id: str) -> dict:
    tenant_id = validate_tenant_id(tenant_id)
    item = store.get(tenant_id)
    if not item:
        raise OnboardError(f"tenant {tenant_id!r} not found")
    if item.get("status") == "ACTIVE":
        return item
    if item.get("status") != "SUSPENDED":
        raise OnboardError(f"cannot resume from status {item.get('status')}")

    outputs = tofu_outputs(str(tofu_dir))
    extra = _cp_identities(store)
    ids, irsa, secrets = merge_identity_maps(outputs, extra)
    if tenant_id not in irsa or tenant_id not in secrets:
        raise OnboardError(
            f"tenant {tenant_id!r} missing identity maps; cannot resume"
        )

    ip = node_ip()
    onboard(
        tenant_id,
        outputs,
        ip,
        tenant_ids=ids,
        irsa_roles=irsa,
        secrets=secrets,
    )
    # Scale explicitly in case helm left replicas alone
    _run(["kubectl", "-n", _ns(tenant_id), "scale", "deploy/test-app", "--replicas=1"])
    _run(
        [
            "kubectl",
            "-n",
            _ns(tenant_id),
            "rollout",
            "status",
            "deploy/test-app",
            "--timeout=180s",
        ]
    )

    alb = (outputs.get("alb_url") or "").rstrip("/")
    if (outputs.get("ingress_mode") or "alb_controller") == "alb_controller":
        host = wait_ingress_hostname(_ns(tenant_id), timeout=300)
        alb = write_alb_url(str(tofu_dir), host)

    return store.upsert(
        tenant_id,
        desired_status="ACTIVE",
        status="ACTIVE",
        endpoint=f"{alb}/tenant-{tenant_id}" if alb else item.get("endpoint"),
        path_prefix=f"/tenant-{tenant_id}",
        error=None,
    )


def _disable_application_access(tenant_id: str) -> None:
    """Cut the product path first so the tenant cannot use credentials during teardown."""
    ns = _ns(tenant_id)
    _run_ok(["kubectl", "-n", ns, "scale", "deploy/test-app", "--replicas=0"])
    _run_ok(["kubectl", "-n", ns, "delete", "ingress", "test-app", "--ignore-not-found"])


def _revoke_postgres_role(outputs: dict, tenant_id: str, *, attempts: int = 3) -> None:
    """NOLOGIN + password rotate + DROP ROLE. Fail closed — do not continue teardown."""
    from pg_admin import drop_postgres_role

    last: Exception | None = None
    for i in range(attempts):
        try:
            drop_postgres_role(outputs, tenant_id)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"! postgres role revoke attempt {i + 1}/{attempts} failed: {exc}", file=sys.stderr)
            if i + 1 < attempts:
                time.sleep(5 * (i + 1))
    raise OnboardError(f"postgres role revoke failed after {attempts} attempts: {last}")


def _delete_kubernetes(ns: str) -> None:
    """Remove the tenant workload. Missing release/ns is OK; a live namespace must go away."""
    _run_ok(["helm", "uninstall", "test-app", "-n", ns])
    exists = (
        subprocess.call(
            ["kubectl", "get", "ns", ns],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        == 0
    )
    if exists:
        _run(["kubectl", "delete", "ns", ns, "--wait=true", "--timeout=180s"])


def delete_tenant(store: TenantStore, tofu_dir: Path, tenant_id: str) -> None:
    """Fail-closed delete. Safe to retry from DELETING or DELETE_FAILED.

    Order: disable access → revoke DB role (authority) → Kubernetes → IRSA → secret.
    If DROP ROLE fails, Kubernetes and AWS identity stay; status is DELETE_FAILED.
    """
    tenant_id = validate_tenant_id(tenant_id)
    item = store.get(tenant_id) or {"id": tenant_id, "owned_by": None}
    store.upsert(tenant_id, desired_status="GONE", status="DELETING", error=None, delete_step="started")
    ns = _ns(tenant_id)
    try:
        _disable_application_access(tenant_id)
        store.upsert(tenant_id, status="DELETING", delete_step="access_disabled", error=None)

        outputs = tofu_outputs(str(tofu_dir))
        _revoke_postgres_role(outputs, tenant_id)
        store.upsert(tenant_id, status="DELETING", delete_step="db_revoked", error=None)

        _delete_kubernetes(ns)
        store.upsert(tenant_id, status="DELETING", delete_step="k8s_deleted", error=None)

        owned = item.get("owned_by")
        if owned == "control_plane":
            delete_tenant_irsa(
                outputs,
                tenant_id,
                role_arn=item.get("irsa_role_arn"),
            )
            store.upsert(tenant_id, status="DELETING", delete_step="iam_deleted", error=None)
            delete_tenant_secret(
                outputs,
                tenant_id,
                secret_name=item.get("secret_name"),
            )
            store.upsert(tenant_id, status="DELETING", delete_step="secret_deleted", error=None)
        elif owned == "opentofu":
            print(
                f"! tenant {tenant_id}: k8s + DB role removed; OpenTofu still owns SM/IRSA "
                f"(remove from tenant_ids + apply to destroy AWS side)",
                file=sys.stderr,
            )

        store.delete(tenant_id)
    except Exception as exc:
        traceback.print_exc()
        store.upsert(
            tenant_id,
            status="DELETE_FAILED",
            desired_status="GONE",
            error=str(exc),
        )
        raise
