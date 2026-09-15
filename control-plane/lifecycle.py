"""Tenant lifecycle: suspend / resume / delete (no env recreate)."""

from __future__ import annotations

import subprocess
import sys
import traceback
from pathlib import Path

from aws_identity import delete_tenant_identity, merge_identity_maps
from onboard_bridge import OnboardError, node_ip, onboard, tofu_outputs, wait_ingress_hostname, write_alb_url
from store import TenantStore


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), file=sys.stderr)
    subprocess.check_call(cmd)


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
    item = store.get(tenant_id)
    if not item:
        raise OnboardError(f"tenant {tenant_id!r} not found")
    status = item.get("status")
    if status == "SUSPENDED":
        return item
    if status not in ("ACTIVE", "FAILED"):
        raise OnboardError(f"cannot suspend from status {status}")

    ns = _ns(tenant_id)
    _run(["kubectl", "-n", ns, "scale", "deploy/test-app", "--replicas=0"])
    _run_ok(["kubectl", "-n", ns, "delete", "ingress", "test-app", "--ignore-not-found"])
    return store.upsert(tenant_id, status="SUSPENDED", error=None)


def resume_tenant(store: TenantStore, tofu_dir: Path, tenant_id: str) -> dict:
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
        status="ACTIVE",
        endpoint=f"{alb}/tenant-{tenant_id}" if alb else item.get("endpoint"),
        path_prefix=f"/tenant-{tenant_id}",
        error=None,
    )


def delete_tenant(store: TenantStore, tofu_dir: Path, tenant_id: str) -> None:
    item = store.get(tenant_id) or {"id": tenant_id, "owned_by": None}
    store.upsert(tenant_id, status="DELETING", error=None)
    ns = _ns(tenant_id)
    try:
        outputs = tofu_outputs(str(tofu_dir))
        # Drop DB role before tearing down identity / while migrator IRSA still works.
        try:
            from pg_admin import drop_postgres_role

            drop_postgres_role(outputs, tenant_id)
        except Exception as exc:  # noqa: BLE001
            print(f"! drop postgres role warning: {exc}", file=sys.stderr)

        _run_ok(["helm", "uninstall", "test-app", "-n", ns])
        _run_ok(["kubectl", "delete", "ns", ns, "--wait=true", "--timeout=180s"])

        owned = item.get("owned_by")
        if owned == "control_plane":
            delete_tenant_identity(
                outputs,
                tenant_id,
                secret_name=item.get("secret_name"),
                role_arn=item.get("irsa_role_arn"),
            )
        elif owned == "opentofu":
            print(
                f"! tenant {tenant_id}: k8s removed; OpenTofu still owns SM/IRSA "
                f"(remove from tenant_ids + apply to destroy AWS side)",
                file=sys.stderr,
            )

        store.delete(tenant_id)
    except Exception:
        traceback.print_exc()
        store.upsert(tenant_id, status="FAILED", error="delete failed; see control-plane logs")
        raise
