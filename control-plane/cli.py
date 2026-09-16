#!/usr/bin/env python3
"""CLI for the tenant control plane (preferred over raw onboard_tenant.py).

  export TOFU_DIR=$PWD/env/dev/workload
  python control-plane/cli.py adopt
  python control-plane/cli.py create g
  python control-plane/cli.py suspend g
  python control-plane/cli.py resume g
  python control-plane/cli.py delete g
  python control-plane/cli.py reconcile
  python control-plane/cli.py reconcile g
  python control-plane/cli.py get g
  python control-plane/cli.py list
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Allow running as `python control-plane/cli.py`
_CP = Path(__file__).resolve().parent
if str(_CP) not in sys.path:
    sys.path.insert(0, str(_CP))

try:
    import boto3  # noqa: F401
except ModuleNotFoundError:
    venv_py = _CP / ".venv" / "bin" / "python"
    print(
        "boto3 not found in this Python.\n"
        f"Use: {venv_py} control-plane/cli.py …\n"
        "Or:  python3 -m venv control-plane/.venv && "
        "control-plane/.venv/bin/pip install -r control-plane/requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1)

from adopt import adopt_tenants
from errors import ControlPlaneError, ValidationError
from ids import validate_tenant_id
from lifecycle import delete_tenant, resume_tenant, suspend_tenant
from provisioner import discover_active, provision
from reconcile import reconcile_all, reconcile_one
from store import TenantStore

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOFU = REPO_ROOT / "env" / "dev" / "workload"
DATA = Path(__file__).resolve().parent / "data" / "tenants.db"


def _tofu_dir(args: argparse.Namespace) -> Path:
    return Path(args.tofu_dir or os.environ.get("TOFU_DIR") or DEFAULT_TOFU).resolve()


def _store() -> TenantStore:
    return TenantStore(DATA)


def _wait(store: TenantStore, tid: str, want: set[str], timeout: int = 600) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        item = store.get(tid)
        if not item and "GONE" in want:
            return {"id": tid, "status": "GONE"}
        if item and item.get("status") in want:
            return item
        if item and item.get("status") in ("FAILED", "DELETE_FAILED"):
            raise SystemExit(f"{item.get('status')}: {item.get('error')}")
        time.sleep(3)
    raise SystemExit(f"timeout waiting for {tid} in {want}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Tenant control plane CLI")
    parser.add_argument("--tofu-dir", default=None, help="Workload stack dir")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_adopt = sub.add_parser("adopt", help="Adopt existing SM/IRSA into CP ownership")
    p_adopt.add_argument("tenants", nargs="*", help="ids (default: discover all tenant-* secrets)")

    p_create = sub.add_parser("create", help="Provision tenant (identity + onboard)")
    p_create.add_argument("tenant")
    p_create.add_argument("--tier", default="standard")
    p_create.add_argument("--ensure-infra", action="store_true")

    for name in ("suspend", "resume", "delete", "get"):
        p = sub.add_parser(name)
        p.add_argument("tenant")

    p_rec = sub.add_parser("reconcile", help="Make actual match desired (drift)")
    p_rec.add_argument("tenant", nargs="?", help="one id; omit to reconcile all")

    sub.add_parser("list")
    sub.add_parser("discover", help="List registry + unmanaged tenant-* namespaces (no auto-ACTIVE)")

    args = parser.parse_args()
    store = _store()
    tofu = _tofu_dir(args)

    def _id(raw: str) -> str:
        try:
            return validate_tenant_id(raw)
        except ValidationError as exc:
            raise SystemExit(str(exc)) from exc

    if args.cmd == "discover":
        print(json.dumps(discover_active(store, tofu), indent=2))
        return 0

    if args.cmd == "reconcile":
        if args.tenant:
            print(json.dumps(reconcile_one(store, tofu, _id(args.tenant)), indent=2, default=str))
        else:
            print(json.dumps(reconcile_all(store, tofu), indent=2, default=str))
        return 0

    if args.cmd == "adopt":
        adopted = adopt_tenants(store, tofu, args.tenants or None)
        print(json.dumps(adopted, indent=2))
        return 0

    if args.cmd == "list":
        print(json.dumps({"tenants": store.list()}, indent=2))
        return 0

    if args.cmd == "get":
        tid = _id(args.tenant)
        item = store.get(tid)
        if not item:
            print(json.dumps({"error": "not_found", "id": tid}))
            return 1
        print(json.dumps(item, indent=2))
        return 0

    if args.cmd == "create":
        tid = _id(args.tenant)
        try:
            provision(
                store,
                tofu,
                tid,
                tier=args.tier,
                ensure_infra_flag=args.ensure_infra,
                ensure_identity_flag=not args.ensure_infra,
                my_ip=os.environ.get("MY_IP"),
            )
        except ControlPlaneError as exc:
            print(json.dumps(store.get(tid) or {"error": str(exc)}, indent=2))
            return 1
        print(json.dumps(store.get(tid), indent=2))
        return 0

    if args.cmd == "suspend":
        print(json.dumps(suspend_tenant(store, _id(args.tenant)), indent=2))
        return 0

    if args.cmd == "resume":
        tid = _id(args.tenant)
        resume_tenant(store, tofu, tid)
        print(json.dumps(store.get(tid), indent=2))
        return 0

    if args.cmd == "delete":
        tid = _id(args.tenant)
        try:
            delete_tenant(store, tofu, tid)
        except ControlPlaneError as exc:
            item = store.get(tid) or {
                "id": tid,
                "status": "DELETE_FAILED",
                "error": str(exc),
            }
            print(json.dumps(item, indent=2))
            return 1
        print(json.dumps({"id": tid, "status": "GONE"}))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
