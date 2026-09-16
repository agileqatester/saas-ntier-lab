"""Adopt existing AWS tenant identity into control-plane ownership (no recreate)."""

from __future__ import annotations

import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from errors import ValidationError
from ids import validate_tenant_id
from onboard_bridge import OnboardError, tofu_outputs
from store import TenantStore


def adopt_tenants(
    store: TenantStore,
    tofu_dir: Path,
    tenant_ids: list[str] | None = None,
) -> list[dict]:
    """Mark tenants as owned_by=control_plane using existing SM secrets + IRSA roles.

    Does not recreate AWS resources. After this, set manage_tenant_identity=false
    and remove matching resources from OpenTofu state so apply does not destroy them.
    """
    outputs = tofu_outputs(str(tofu_dir))
    region = outputs.get("aws_region") or "us-east-1"
    prefix = outputs.get("name_prefix") or "ntier-dev"
    alb = (outputs.get("alb_url") or "").rstrip("/")
    if not alb:
        try:
            alb = (tofu_dir / ".alb_url").read_text().strip()
        except OSError:
            alb = ""

    ids = tenant_ids
    if not ids:
        # Discover tenant-* secrets
        sm = boto3.client("secretsmanager", region_name=region)
        ids = []
        token = None
        while True:
            kwargs = {"MaxResults": 100}
            if token:
                kwargs["NextToken"] = token
            resp = sm.list_secrets(**kwargs)
            for sec in resp.get("SecretList", []):
                name = sec.get("Name") or ""
                marker = f"{prefix}/rds/tenant-"
                if name.startswith(marker):
                    tid = name[len(marker) :]
                    if tid and tid not in ids:
                        ids.append(tid)
            token = resp.get("NextToken")
            if not token:
                break
        ids.sort()

    if not ids:
        raise OnboardError("no tenant secrets found to adopt")

    iam = boto3.client("iam", region_name=region)
    sm = boto3.client("secretsmanager", region_name=region)
    adopted = []
    for tid in ids:
        try:
            tid = validate_tenant_id(tid)
        except ValidationError:
            print(f"! skip {tid}: invalid tenant id", file=sys.stderr)
            continue
        secret_name = f"{prefix}/rds/tenant-{tid}"
        role_name = f"{prefix}-tenant-{tid}"
        try:
            sm.describe_secret(SecretId=secret_name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                print(f"! skip {tid}: secret missing", file=sys.stderr)
                continue
            raise
        try:
            role = iam.get_role(RoleName=role_name)["Role"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchEntity":
                print(f"! skip {tid}: IRSA role missing", file=sys.stderr)
                continue
            raise

        # Tag for ownership clarity (best-effort)
        try:
            sm.tag_resource(
                SecretId=secret_name,
                Tags=[
                    {"Key": "ManagedBy", "Value": "tenant-control-plane"},
                    {"Key": "Tenant", "Value": tid},
                ],
            )
            iam.tag_role(
                RoleName=role_name,
                Tags=[
                    {"Key": "ManagedBy", "Value": "tenant-control-plane"},
                    {"Key": "Tenant", "Value": tid},
                ],
            )
        except ClientError as exc:
            print(f"! tag warning {tid}: {exc}", file=sys.stderr)

        existing = store.get(tid) or {}
        item = store.upsert(
            tid,
            desired_status=existing.get("desired_status") or "ACTIVE",
            status=existing.get("status") or "ACTIVE",
            tier=existing.get("tier") or "standard",
            owned_by="control_plane",
            secret_name=secret_name,
            irsa_role_arn=role["Arn"],
            endpoint=f"{alb}/tenant-{tid}" if alb else existing.get("endpoint"),
            path_prefix=f"/tenant-{tid}",
            error=None,
        )
        adopted.append(item)
        print(f"+ adopted {tid} -> control_plane ({secret_name})", file=sys.stderr)
    return adopted
