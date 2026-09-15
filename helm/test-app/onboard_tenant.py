#!/usr/bin/env python3
"""Kubernetes onboard for one pooled tenant. IAM/secrets stay in OpenTofu.

Looks up IRSA role ARNs and secret names from `tofu output -json` in the
workload stack. Do not export IRSA_* / SECRET_* by hand.

Edge (tofu output ingress_mode):
  alb_controller — ClusterIP + Ingress (shared ALB group)
  nodeport       — NodePort 30080+index (legacy lab ALB)

Run from env/dev/workload after apply (enable_rds = true):

  python3 ../../../helm/test-app/onboard_tenant.py --all
  python3 ../../../helm/test-app/onboard_tenant.py c
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

CHART_DIR = os.path.dirname(os.path.abspath(__file__))


class OnboardError(Exception):
    """Raised when onboard cannot proceed (missing tofu outputs, kubectl, etc.)."""


def run(cmd: list[str], **kwargs) -> None:
    print("+", " ".join(cmd), file=sys.stderr)
    subprocess.check_call(cmd, **kwargs)


def run_out(cmd: list[str], **kwargs) -> str:
    return subprocess.check_output(cmd, text=True, **kwargs).strip()


def tofu_bin() -> str:
    for name in ("tofu", "terraform"):
        path = shutil.which(name)
        if path:
            return path
    raise OnboardError("tofu (or terraform) not found on PATH")


def tofu_outputs(tofu_dir: str) -> dict:
    print("+ tofu output -json", file=sys.stderr)
    raw = run_out([tofu_bin(), "output", "-json"], cwd=tofu_dir)
    parsed = json.loads(raw)
    return {key: item["value"] for key, item in parsed.items()}


def node_ip() -> str:
    ip = os.environ.get("NODE_IP")
    if ip:
        return ip
    ip = run_out(
        [
            "kubectl",
            "get",
            "nodes",
            "-o",
            "jsonpath={.items[0].status.addresses[?(@.type==\"InternalIP\")].address}",
        ]
    )
    if not ip:
        region = os.environ.get("AWS_REGION", "us-east-1")
        raise OnboardError(
            "no Ready node. Refresh kubeconfig, wait, retry:\n"
            f"  aws eks update-kubeconfig --name ntier-dev-eks-cluster --region {region}\n"
            "  kubectl wait --for=condition=Ready nodes --all --timeout=600s"
        )
    return ip


def require(outputs: dict, key: str):
    value = outputs.get(key)
    if value in (None, "", {}, []):
        raise OnboardError(
            f"tofu output {key!r} is empty. Is enable_rds true? Apply from env/dev/workload."
        )
    return value


def wait_ingress_hostname(ns: str, name: str = "test-app", timeout: int = 600) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        host = run_out(
            [
                "kubectl",
                "-n",
                ns,
                "get",
                "ingress",
                name,
                "-o",
                "jsonpath={.status.loadBalancer.ingress[0].hostname}",
            ]
        )
        if host:
            return host
        time.sleep(5)
    raise OnboardError(f"timed out waiting for Ingress {ns}/{name} ADDRESS")


def write_alb_url(tofu_dir: str, host: str) -> str:
    url = f"http://{host}"
    path = os.path.join(tofu_dir, ".alb_url")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(url + "\n")
    print(f"+ wrote {path} -> {url}", file=sys.stderr)
    return url


def onboard(
    tenant: str,
    outputs: dict,
    ip: str,
    *,
    tenant_ids: list[str] | None = None,
    irsa_roles: dict | None = None,
    secrets: dict | None = None,
) -> None:
    tenant_ids = list(tenant_ids if tenant_ids is not None else require(outputs, "tenant_ids"))
    irsa_roles = dict(
        irsa_roles if irsa_roles is not None else require(outputs, "tenant_irsa_role_arns")
    )
    secrets = dict(secrets if secrets is not None else require(outputs, "tenant_secret_names"))
    if tenant not in irsa_roles or tenant not in secrets:
        raise OnboardError(
            f"tenant {tenant!r} missing IRSA/secret maps "
            f"(irsa={sorted(irsa_roles)}, secrets={sorted(secrets)}). "
            "Provision identity via control plane or tofu apply."
        )
    if tenant not in tenant_ids:
        tenant_ids = [*tenant_ids, tenant]

    mode = outputs.get("ingress_mode") or "alb_controller"
    first = (
        outputs.get("platform_tenant_id")
        or (tenant_ids[0] if tenant_ids else "a")
    )
    ns = f"tenant-{tenant}"
    region = outputs.get("aws_region") or os.environ.get("AWS_REGION") or "us-east-1"
    host = require(outputs, "rds_host")
    irsa = irsa_roles[tenant]
    secret = secrets[tenant]
    ann = json.dumps({"eks.amazonaws.com/role-arn": irsa})
    path_prefix = f"/tenant-{tenant}"

    if mode == "alb_controller":
        pub_cidrs = outputs.get("public_subnet_cidrs") or []
        if not pub_cidrs:
            raise OnboardError(
                "tofu output public_subnet_cidrs is empty; needed for NetworkPolicy with alb_controller"
            )
        my_ip = os.environ.get("MY_IP") or outputs.get("my_ip_cidr") or ""
        inbound = [c for c in [my_ip] if c]
        np_cidrs = list(pub_cidrs)
        group = outputs.get("alb_ingress_group") or outputs.get("name_prefix") or "ntier-dev"
        try:
            order = str((tenant_ids.index(tenant) + 1) * 10)
        except ValueError:
            order = str(900 + (sum(ord(c) for c in tenant) % 90))
        logs_bucket = outputs.get("alb_logs_bucket") or ""
        edge_sets = [
            "--set",
            "service.type=ClusterIP",
            "--set",
            "ingress.enabled=true",
            "--set",
            f"ingress.groupName={group}",
            "--set",
            f"ingress.groupOrder={order}",
            "--set-json",
            f"ingress.inboundCidrs={json.dumps(inbound)}",
            "--set-json",
            f"networkPolicy.ingressCidrs={json.dumps(np_cidrs)}",
        ]
        if logs_bucket:
            edge_sets += ["--set", f"ingress.accessLogsBucket={logs_bucket}"]
    else:
        ports = require(outputs, "tenant_node_ports")
        if tenant not in ports:
            raise OnboardError(f"tenant {tenant!r} missing from tenant_node_ports")
        node_port = int(ports[tenant])
        edge_sets = [
            "--set",
            "service.type=NodePort",
            "--set",
            f"service.nodePort={node_port}",
            "--set",
            "ingress.enabled=false",
            "--set-json",
            f"networkPolicy.ingressCidrs={json.dumps([f'{ip}/32'])}",
        ]

    ns_yaml = run_out(["kubectl", "create", "namespace", ns, "--dry-run=client", "-o", "yaml"])
    print(f"+ kubectl apply -f -  # namespace {ns}", file=sys.stderr)
    subprocess.run(["kubectl", "apply", "-f", "-"], input=ns_yaml, text=True, check=True)
    run(["kubectl", "label", "ns", ns, f"tenant={tenant}", "--overwrite"])

    helm = [
        "helm",
        "upgrade",
        "--install",
        "test-app",
        CHART_DIR,
        "-n",
        ns,
        "--set",
        "fullnameOverride=test-app",
        "--set",
        "serviceAccount.name=test-app",
        "--set",
        f"tenant.id={tenant}",
        "--set",
        f"pathPrefix={path_prefix}",
        "--set",
        "quota.enabled=true",
        "--set",
        "networkPolicy.enabled=true",
        "--set-json",
        f"serviceAccount.annotations={ann}",
        "--set",
        "database.enabled=true",
        "--set",
        f"database.host={host}",
        "--set",
        f"database.secretName={secret}",
        "--set",
        f"region={region}",
        *edge_sets,
    ]

    if tenant == first:
        run(["kubectl", "-n", ns, "delete", "job", "test-app-migrate", "--ignore-not-found"])
        migrator = require(outputs, "migrator_irsa_role_arn")
        master = require(outputs, "rds_secret_name")
        mig_ann = json.dumps({"eks.amazonaws.com/role-arn": migrator})
        helm += [
            "--set",
            "database.migrate=true",
            "--set-json",
            f"database.migratorServiceAccount.annotations={mig_ann}",
            "--set",
            f"database.masterSecret={master}",
            "--set-json",
            f"database.tenantSecrets={json.dumps(secrets)}",
        ]
    else:
        helm += ["--set", "database.migrate=false"]

    run(helm)

    if tenant == first:
        run(
            [
                "kubectl",
                "-n",
                ns,
                "wait",
                "--for=condition=complete",
                "job/test-app-migrate",
                "--timeout=300s",
            ]
        )

    if mode == "alb_controller":
        print(f"onboarded {ns} (ClusterIP + Ingress group, path {path_prefix})")
    else:
        print(f"onboarded {ns} (node {ip}, NodePort {ports[tenant]})")


def onboard_tenant(
    tenant: str,
    tofu_dir: str = ".",
    *,
    tenant_ids: list[str] | None = None,
    irsa_roles: dict | None = None,
    secrets: dict | None = None,
) -> None:
    """Onboard one tenant (and re-run first tenant migrate when adding a new id)."""
    outputs = tofu_outputs(tofu_dir)
    ip = node_ip()
    ids = list(tenant_ids if tenant_ids is not None else (outputs.get("tenant_ids") or []))
    platform = outputs.get("platform_tenant_id") or (ids[0] if ids else "a")
    if tenant not in ids:
        ids = [*ids, tenant]
    if platform not in ids:
        ids = [platform, *ids]
    irsa = dict(irsa_roles if irsa_roles is not None else (outputs.get("tenant_irsa_role_arns") or {}))
    secs = dict(secrets if secrets is not None else (outputs.get("tenant_secret_names") or {}))
    if tenant != platform:
        tenants = [platform, tenant]
    else:
        tenants = [tenant]
    for tid in tenants:
        onboard(
            tid,
            outputs,
            ip,
            tenant_ids=ids,
            irsa_roles=irsa,
            secrets=secs,
        )
    if (outputs.get("ingress_mode") or "alb_controller") == "alb_controller":
        host = wait_ingress_hostname(f"tenant-{tenant}")
        write_alb_url(tofu_dir, host)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "DEPRECATED: use `python control-plane/cli.py create <id>` instead. "
            "This wrapper still onboards via the shared library."
        )
    )
    parser.add_argument(
        "tenant",
        nargs="?",
        help="tenant id (omit with --all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="onboard every id in tofu output tenant_ids (legacy)",
    )
    parser.add_argument(
        "--tofu-dir",
        default=".",
        help="OpenTofu stack directory (default: cwd; run from env/dev/workload)",
    )
    args = parser.parse_args()
    if bool(args.tenant) == args.all:
        parser.error("pass a tenant id or --all")

    print(
        "warning: onboard_tenant.py is deprecated; prefer "
        "`python control-plane/cli.py create <id>`",
        file=sys.stderr,
    )

    try:
        outputs = tofu_outputs(args.tofu_dir)
        ip = node_ip()
        ids = list(outputs.get("tenant_ids") or [])
        platform = outputs.get("platform_tenant_id") or (ids[0] if ids else "a")
        irsa = dict(outputs.get("tenant_irsa_role_arns") or {})
        secs = dict(outputs.get("tenant_secret_names") or {})
        # Merge any CP-owned identities from the registry if present
        try:
            from pathlib import Path

            reg = Path(__file__).resolve().parents[2] / "control-plane" / "data" / "tenants.json"
            if reg.exists():
                import json as _json

                raw = _json.loads(reg.read_text())
                for tid, meta in (raw.get("tenants") or {}).items():
                    if meta.get("irsa_role_arn"):
                        irsa[tid] = meta["irsa_role_arn"]
                    if meta.get("secret_name"):
                        secs[tid] = meta["secret_name"]
                    if tid not in ids:
                        ids.append(tid)
        except Exception as exc:  # noqa: BLE001
            print(f"registry merge skip: {exc}", file=sys.stderr)

        if args.all:
            tenants = ids or [platform]
        elif args.tenant != platform:
            tenants = [platform, args.tenant]
            if args.tenant not in ids:
                ids = [*ids, args.tenant]
        else:
            tenants = [args.tenant]
        if platform not in ids:
            ids = [platform, *ids]
        for tid in tenants:
            onboard(
                tid,
                outputs,
                ip,
                tenant_ids=ids,
                irsa_roles=irsa,
                secrets=secs,
            )
        if (outputs.get("ingress_mode") or "alb_controller") == "alb_controller":
            host = wait_ingress_hostname(f"tenant-{tenants[-1]}")
            url = write_alb_url(args.tofu_dir, host)
            print(url)
    except OnboardError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"command failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
