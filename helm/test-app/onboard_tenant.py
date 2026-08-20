#!/usr/bin/env python3
"""Kubernetes onboard for one pooled tenant. IAM/secrets stay in OpenTofu.

Looks up IRSA role ARNs and secret names from `tofu output -json` in the
workload stack. Do not export IRSA_* / SECRET_* by hand.

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

CHART_DIR = os.path.dirname(os.path.abspath(__file__))


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
    sys.exit("tofu (or terraform) not found on PATH")


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
        print("no Ready node. Refresh kubeconfig, wait, retry:", file=sys.stderr)
        print(
            f"  aws eks update-kubeconfig --name ntier-dev-eks-cluster --region {region}",
            file=sys.stderr,
        )
        print("  kubectl wait --for=condition=Ready nodes --all --timeout=600s", file=sys.stderr)
        sys.exit(1)
    return ip


def require(outputs: dict, key: str):
    value = outputs.get(key)
    if value in (None, "", {}, []):
        sys.exit(f"tofu output {key!r} is empty. Is enable_rds true? Apply from env/dev/workload.")
    return value


def onboard(tenant: str, outputs: dict, ip: str) -> None:
    tenant_ids = require(outputs, "tenant_ids")
    irsa_roles = require(outputs, "tenant_irsa_role_arns")
    secrets = require(outputs, "tenant_secret_names")
    ports = require(outputs, "tenant_node_ports")
    if tenant not in tenant_ids:
        sys.exit(f"tenant {tenant!r} is not in tenant_ids={tenant_ids}. Add it to var.tenant_ids and apply.")
    if tenant not in irsa_roles or tenant not in secrets or tenant not in ports:
        sys.exit(f"tenant {tenant!r} missing from tofu IRSA/secret/node-port maps. Apply after changing tenant_ids.")

    first = tenant_ids[0]
    ns = f"tenant-{tenant}"
    region = outputs.get("aws_region") or os.environ.get("AWS_REGION") or "us-east-1"
    host = require(outputs, "rds_host")
    irsa = irsa_roles[tenant]
    secret = secrets[tenant]
    node_port = int(ports[tenant])
    ann = json.dumps({"eks.amazonaws.com/role-arn": irsa})

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
        f"pathPrefix=/tenant-{tenant}",
        "--set",
        "service.type=NodePort",
        "--set",
        f"service.nodePort={node_port}",
        "--set",
        "quota.enabled=true",
        "--set",
        "networkPolicy.enabled=true",
        "--set-json",
        f"networkPolicy.ingressCidrs={json.dumps([f'{ip}/32'])}",
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

    print(f"onboarded {ns} (node {ip}, NodePort {node_port})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Onboard a pooled tenant using tofu outputs (no IRSA_* env vars)."
    )
    parser.add_argument(
        "tenant",
        nargs="?",
        help="tenant id from var.tenant_ids (omit with --all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="onboard every id in tofu output tenant_ids (first id runs migrate)",
    )
    parser.add_argument(
        "--tofu-dir",
        default=".",
        help="OpenTofu stack directory (default: cwd; run from env/dev/workload)",
    )
    args = parser.parse_args()
    if bool(args.tenant) == args.all:
        parser.error("pass a tenant id or --all")

    outputs = tofu_outputs(args.tofu_dir)
    ip = node_ip()
    ids = require(outputs, "tenant_ids")
    if args.all:
        tenants = ids
    elif args.tenant != ids[0]:
        # New ids need a migrate Job that sees every secret. First tenant owns that Job.
        tenants = [ids[0], args.tenant]
    else:
        tenants = [args.tenant]
    for tid in tenants:
        onboard(tid, outputs, ip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
