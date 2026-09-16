"""Create per-tenant Secrets Manager secret + IRSA role (no tofu apply)."""

from __future__ import annotations

import json
import secrets
import string
import sys
from typing import Any

import boto3
from botocore.exceptions import ClientError

from errors import classify_aws_error, with_retry
from ids import validate_tenant_id
from onboard_bridge import OnboardError
from safety import secret_recovery_window_days


def _password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!#$%&*()-_=+[]{}<>:?"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _iam(region: str):
    return boto3.client("iam", region_name=region)


def _sm(region: str):
    return boto3.client("secretsmanager", region_name=region)


def _sts(region: str):
    return boto3.client("sts", region_name=region)


def _raise_aws(exc: ClientError) -> None:
    err = exc.response.get("Error") or {}
    raise classify_aws_error(str(err.get("Code") or "Unknown"), str(err.get("Message") or exc)) from exc


def ensure_tenant_identity(outputs: dict, tenant_id: str) -> dict[str, str]:
    tenant_id = validate_tenant_id(tenant_id)

    def _op() -> dict[str, str]:
        try:
            return _ensure_tenant_identity(outputs, tenant_id)
        except ClientError as exc:
            _raise_aws(exc)
            raise

    return with_retry(_op)


def _ensure_tenant_identity(outputs: dict, tenant_id: str) -> dict[str, str]:
    """Idempotently create SM secret + IRSA role for tenant_id.

    Returns {"secret_name", "irsa_role_arn", "owned_by": "control_plane"}.
    Does not recreate EKS/RDS or touch OpenTofu-managed tenants.
    """
    region = outputs.get("aws_region") or "us-east-1"
    prefix = outputs.get("name_prefix") or "ntier-dev"
    host = outputs.get("rds_host")
    if not host:
        raise OnboardError("tofu output rds_host is empty")

    oidc_arn = outputs.get("oidc_provider_arn")
    oidc_url = outputs.get("oidc_provider_url")
    if not oidc_arn or not oidc_url:
        raise OnboardError(
            "tofu outputs oidc_provider_arn / oidc_provider_url required for IRSA"
        )

    secret_name = f"{prefix}/rds/tenant-{tenant_id}"
    role_name = f"{prefix}-tenant-{tenant_id}"
    account = _sts(region).get_caller_identity()["Account"]

    sm = _sm(region)
    password = _password()
    payload = {
        "username": f"tenant_{tenant_id}",
        "password": password,
        "host": host,
        "port": 5432,
        "dbname": "postgres",
        "tenant_id": tenant_id,
    }

    try:
        desc = sm.describe_secret(SecretId=secret_name)
        if desc.get("DeletedDate"):
            # Finish pending deletion so we can recreate with a fresh password.
            try:
                sm.delete_secret(SecretId=secret_name, ForceDeleteWithoutRecovery=True)
            except ClientError:
                pass
            waiter_deadline = __import__("time").time() + 120
            while __import__("time").time() < waiter_deadline:
                try:
                    sm.describe_secret(SecretId=secret_name)
                    __import__("time").sleep(2)
                except ClientError as wait_exc:
                    if wait_exc.response["Error"]["Code"] == "ResourceNotFoundException":
                        break
                    raise
            created = sm.create_secret(
                Name=secret_name,
                SecretString=json.dumps(payload),
                Tags=[
                    {"Key": "ManagedBy", "Value": "tenant-control-plane"},
                    {"Key": "Tenant", "Value": tenant_id},
                ],
            )
            secret_arn = created["ARN"]
            print(f"+ recreated secret {secret_name} after pending delete", file=sys.stderr)
        else:
            secret_arn = desc["ARN"]
            print(f"+ secret {secret_name} already exists", file=sys.stderr)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        created = sm.create_secret(
            Name=secret_name,
            SecretString=json.dumps(payload),
            Tags=[
                {"Key": "ManagedBy", "Value": "tenant-control-plane"},
                {"Key": "Tenant", "Value": tenant_id},
            ],
        )
        secret_arn = created["ARN"]
        print(f"+ created secret {secret_name}", file=sys.stderr)

    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Federated": oidc_arn},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        f"{oidc_url}:sub": f"system:serviceaccount:tenant-{tenant_id}:test-app",
                        f"{oidc_url}:aud": "sts.amazonaws.com",
                    }
                },
            }
        ],
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadOwnTenantSecret",
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret",
                ],
                "Resource": secret_arn,
            }
        ],
    }

    iam = _iam(region)
    try:
        role = iam.get_role(RoleName=role_name)["Role"]
        iam.update_assume_role_policy(
            RoleName=role_name, PolicyDocument=json.dumps(trust)
        )
        print(f"+ updated IRSA role {role_name}", file=sys.stderr)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        role = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description=f"IRSA for pooled tenant {tenant_id} (control plane)",
            Tags=[
                {"Key": "ManagedBy", "Value": "tenant-control-plane"},
                {"Key": "Tenant", "Value": tenant_id},
            ],
        )["Role"]
        print(f"+ created IRSA role {role_name}", file=sys.stderr)

    iam.put_role_policy(
        RoleName=role_name,
        PolicyName=f"{prefix}-tenant-{tenant_id}-secrets",
        PolicyDocument=json.dumps(policy),
    )

    return {
        "secret_name": secret_name,
        "irsa_role_arn": role["Arn"],
        "owned_by": "control_plane",
        "account": account,
    }


def merge_identity_maps(
    outputs: dict,
    extra: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Merge tofu maps with control-plane-owned identities."""
    ids = list(outputs.get("tenant_ids") or [])
    irsa = dict(outputs.get("tenant_irsa_role_arns") or {})
    secrets = dict(outputs.get("tenant_secret_names") or {})
    for tid, meta in sorted(extra.items()):
        if tid not in ids:
            ids.append(tid)
        if meta.get("irsa_role_arn"):
            irsa[tid] = meta["irsa_role_arn"]
        if meta.get("secret_name"):
            secrets[tid] = meta["secret_name"]
    return ids, irsa, secrets


def delete_tenant_irsa(
    outputs: dict,
    tenant_id: str,
    *,
    role_arn: str | None = None,
) -> None:
    """Delete the tenant IRSA role. Idempotent if already gone."""
    tenant_id = validate_tenant_id(tenant_id)
    region = outputs.get("aws_region") or "us-east-1"
    prefix = outputs.get("name_prefix") or "ntier-dev"
    role_name = f"{prefix}-tenant-{tenant_id}"
    if role_arn and role_arn.startswith("arn:"):
        role_name = role_arn.rsplit("/", 1)[-1]

    iam = _iam(region)
    policy_name = f"{prefix}-tenant-{tenant_id}-secrets"
    try:
        iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            _raise_aws(exc)
    try:
        iam.delete_role(RoleName=role_name)
        print(f"+ deleted IRSA role {role_name}", file=sys.stderr)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            _raise_aws(exc)
        print(f"+ IRSA role {role_name} already gone", file=sys.stderr)


def delete_tenant_secret(
    outputs: dict,
    tenant_id: str,
    *,
    secret_name: str | None = None,
) -> None:
    """Delete the tenant secret. Lab default is force-delete; production should use a recovery window.

    This does not revoke a live DB password. Disable/DROP the Postgres role first.
    """
    tenant_id = validate_tenant_id(tenant_id)
    region = outputs.get("aws_region") or "us-east-1"
    prefix = outputs.get("name_prefix") or "ntier-dev"
    secret_name = secret_name or f"{prefix}/rds/tenant-{tenant_id}"
    sm = _sm(region)
    try:
        days = secret_recovery_window_days()
        if days:
            sm.delete_secret(SecretId=secret_name, RecoveryWindowInDays=days)
            print(f"+ scheduled secret delete {secret_name} (recovery {days}d)", file=sys.stderr)
        else:
            sm.delete_secret(SecretId=secret_name, ForceDeleteWithoutRecovery=True)
            print(f"+ force-deleted secret {secret_name} (lab)", file=sys.stderr)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code not in ("ResourceNotFoundException", "InvalidRequestException"):
            _raise_aws(exc)
        print(f"+ secret {secret_name} already gone ({code})", file=sys.stderr)


def delete_tenant_identity(
    outputs: dict,
    tenant_id: str,
    *,
    secret_name: str | None = None,
    role_arn: str | None = None,
) -> None:
    """Delete CP-owned IRSA then SM secret. Idempotent if already gone.

    Order: IAM first (workload can no longer read the secret), then the secret.
    """
    delete_tenant_irsa(outputs, tenant_id, role_arn=role_arn)
    delete_tenant_secret(outputs, tenant_id, secret_name=secret_name)
