"""Provisioner: AWS identity (SM+IRSA) + k8s onboard. Optional legacy tofu apply."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from errors import ControlPlaneError, PermanentProvisioningError
from ids import validate_tenant_id
from aws_identity import ensure_tenant_identity, merge_identity_maps
from infra import ensure_infra
from onboard_bridge import OnboardError, node_ip, onboard, require, tofu_outputs, wait_ingress_hostname, write_alb_url
from store import TenantStore


def _cp_identities(store: TenantStore) -> dict:
    out = {}
    for item in store.list():
        tid = item.get("id")
        if not tid:
            continue
        if item.get("owned_by") == "control_plane" and item.get("secret_name") and item.get(
            "irsa_role_arn"
        ):
            out[tid] = {
                "secret_name": item["secret_name"],
                "irsa_role_arn": item["irsa_role_arn"],
                "owned_by": "control_plane",
            }
    return out


def discover_active(store: TenantStore, tofu_dir: Path) -> dict:
    """List registry + tenant-* namespaces not in the registry.

    Does **not** promote a namespace to ACTIVE. Use `cli.py reconcile`.
    """
    from reconcile import list_unmanaged_namespaces

    unmanaged = list_unmanaged_namespaces(store)
    if unmanaged:
        print(f"! unmanaged namespaces (not auto-ACTIVE): {unmanaged}", file=sys.stderr)
    return {"tenants": store.list(), "unmanaged_namespaces": unmanaged}


def provision(
    store: TenantStore,
    tofu_dir: Path,
    tenant_id: str,
    *,
    tier: str = "standard",
    ensure_infra_flag: bool = False,
    ensure_identity_flag: bool = True,
    my_ip: str | None = None,
) -> None:
    tenant_id = validate_tenant_id(tenant_id)
    store.upsert(
        tenant_id,
        desired_status="ACTIVE",
        status="PROVISIONING",
        tier=tier,
        error=None,
    )
    try:
        if ensure_infra_flag:
            # Legacy path: edit tfvars + tofu apply (still creates SM/IRSA in OpenTofu).
            outputs = ensure_infra(tofu_dir, tenant_id, my_ip=my_ip)
            identity = {
                "secret_name": (outputs.get("tenant_secret_names") or {}).get(tenant_id),
                "irsa_role_arn": (outputs.get("tenant_irsa_role_arns") or {}).get(tenant_id),
                "owned_by": "opentofu",
            }
        else:
            outputs = tofu_outputs(str(tofu_dir))
            if ensure_identity_flag:
                identity = ensure_tenant_identity(outputs, tenant_id)
            else:
                # Must already exist in tofu maps
                secs = require(outputs, "tenant_secret_names")
                roles = require(outputs, "tenant_irsa_role_arns")
                if tenant_id not in secs or tenant_id not in roles:
                    raise OnboardError(
                        f"tenant {tenant_id!r} missing from tofu identity maps; "
                        "POST with ensure_identity=true (default) or ensure_infra=true"
                    )
                identity = {
                    "secret_name": secs[tenant_id],
                    "irsa_role_arn": roles[tenant_id],
                    "owned_by": "opentofu",
                }

        store.upsert(
            tenant_id,
            desired_status="ACTIVE",
            status="PROVISIONING",
            tier=tier,
            owned_by=identity.get("owned_by"),
            secret_name=identity.get("secret_name"),
            irsa_role_arn=identity.get("irsa_role_arn"),
            error=None,
        )

        extra = _cp_identities(store)
        if identity.get("owned_by") == "control_plane":
            extra[tenant_id] = identity
        ids, irsa, secrets = merge_identity_maps(outputs, extra)

        ip = node_ip()
        first = outputs.get("platform_tenant_id") or (ids[0] if ids else "a")
        # Refresh migrate on platform tenant so Postgres roles include the new secret.
        if tenant_id != first:
            onboard(
                first,
                outputs,
                ip,
                tenant_ids=ids,
                irsa_roles=irsa,
                secrets=secrets,
            )
        onboard(
            tenant_id,
            outputs,
            ip,
            tenant_ids=ids,
            irsa_roles=irsa,
            secrets=secrets,
        )

        if (outputs.get("ingress_mode") or "alb_controller") == "alb_controller":
            host = wait_ingress_hostname(f"tenant-{tenant_id}")
            alb = write_alb_url(str(tofu_dir), host)
        else:
            alb = (outputs.get("alb_url") or "").rstrip("/")

        store.upsert(
            tenant_id,
            desired_status="ACTIVE",
            status="ACTIVE",
            tier=tier,
            endpoint=f"{alb}/tenant-{tenant_id}" if alb else None,
            path_prefix=f"/tenant-{tenant_id}",
            owned_by=identity.get("owned_by"),
            secret_name=identity.get("secret_name"),
            irsa_role_arn=identity.get("irsa_role_arn"),
            error=None,
        )
    except ControlPlaneError as exc:
        traceback.print_exc()
        store.upsert(
            tenant_id,
            desired_status="ACTIVE",
            status="FAILED",
            tier=tier,
            error=str(exc),
        )
        raise
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        store.upsert(
            tenant_id,
            desired_status="ACTIVE",
            status="FAILED",
            tier=tier,
            error=str(exc),
        )
        raise PermanentProvisioningError(str(exc)) from exc
