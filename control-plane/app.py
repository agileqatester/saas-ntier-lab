#!/usr/bin/env python3
"""Tenant Control Plane — create + lifecycle (suspend/resume/delete).

Lab default binds 127.0.0.1 with no token. Non-loopback requires CP_API_TOKEN.

  control-plane/.venv/bin/python control-plane/app.py

  curl -sS -X POST http://127.0.0.1:8088/tenants -H 'Content-Type: application/json' -d '{"id":"f"}'
  curl -sS -X POST http://127.0.0.1:8088/tenants/f/suspend
  curl -sS -X POST http://127.0.0.1:8088/tenants/f/resume
  curl -sS -X DELETE http://127.0.0.1:8088/tenants/f
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, request

from errors import ControlPlaneError, ValidationError
from ids import validate_tenant_id
from lifecycle import delete_tenant, resume_tenant, suspend_tenant
from onboard_bridge import OnboardError
from provisioner import discover_active, provision
from reconcile import reconcile_all, reconcile_one
from safety import assert_bind_safety, authorize_http, BindUnsafeError, configured_token
from store import TenantStore

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOFU_DIR = REPO_ROOT / "env" / "dev" / "workload"
DATA_DIR = Path(__file__).resolve().parent / "data"

app = Flask(__name__)
store = TenantStore(DATA_DIR / "tenants.db")
_tofu_dir = Path(os.environ.get("TOFU_DIR", str(DEFAULT_TOFU_DIR))).resolve()
_provision_lock = threading.Lock()
_inflight: set[str] = set()


def _public(tenant: dict) -> dict:
    return {
        "id": tenant.get("id"),
        "desired_status": tenant.get("desired_status"),
        "status": tenant.get("status"),
        "tier": tenant.get("tier"),
        "endpoint": tenant.get("endpoint"),
        "path_prefix": tenant.get("path_prefix"),
        "owned_by": tenant.get("owned_by"),
        "secret_name": tenant.get("secret_name"),
        "error": tenant.get("error"),
        "delete_step": tenant.get("delete_step"),
        "version": tenant.get("version"),
        "created_at": tenant.get("created_at"),
        "updated_at": tenant.get("updated_at"),
    }


def _flag(body: dict, key: str, default: bool) -> bool:
    val = body.get(key, default)
    if isinstance(val, str):
        return val.lower() in ("1", "true", "yes")
    return bool(val)


@app.before_request
def require_cp_auth():
    decision = authorize_http(
        path=request.path,
        authorization=request.headers.get("Authorization"),
        token=configured_token(),
    )
    if decision is None:
        return None
    status, body = decision
    return jsonify(body), status


@app.errorhandler(ControlPlaneError)
def _cp_error(exc: ControlPlaneError):
    return jsonify({"error": type(exc).__name__, "message": str(exc)}), exc.http_status


def _start_job(tenant_id: str, status: str, fn) -> tuple[dict, int]:
    with _provision_lock:
        if tenant_id in _inflight:
            item = store.get(tenant_id) or {"id": tenant_id, "status": status}
            return _public(item), 202
        _inflight.add(tenant_id)

    def _run() -> None:
        try:
            fn()
        finally:
            with _provision_lock:
                _inflight.discard(tenant_id)

    threading.Thread(target=_run, name=f"lifecycle-{tenant_id}", daemon=True).start()
    item = store.get(tenant_id) or {"id": tenant_id, "status": status}
    return _public(item), 202


@app.get("/health")
def health():
    return jsonify({"status": "ok", "tofu_dir": str(_tofu_dir)})


@app.get("/tenants")
def list_tenants():
    return jsonify({"tenants": [_public(t) for t in store.list()]})


@app.get("/tenants/<tenant_id>")
def get_tenant(tenant_id: str):
    tenant_id = validate_tenant_id(tenant_id)
    item = store.get(tenant_id)
    if not item:
        return jsonify({"error": "not_found", "id": tenant_id}), 404
    return jsonify(_public(item))


@app.post("/tenants")
def create_tenant():
    body = request.get_json(silent=True) or {}
    tenant_id = str(body.get("id", "")).strip()
    try:
        tenant_id = validate_tenant_id(tenant_id)
    except ValidationError as exc:
        return jsonify({"error": "invalid_id", "message": str(exc)}), 400

    tier = str(body.get("tier") or "standard").strip() or "standard"
    ensure_identity = _flag(body, "ensure_identity", True)
    ensure_infra = _flag(body, "ensure_infra", False)

    existing = store.get(tenant_id)
    if existing and existing.get("status") == "ACTIVE":
        return jsonify(_public(existing)), 200
    if existing and existing.get("status") in ("PROVISIONING", "DELETING"):
        return jsonify(_public(existing)), 202
    if existing and existing.get("status") == "DELETE_FAILED":
        return (
            jsonify(
                {
                    "error": "delete_failed",
                    "message": "retry DELETE /tenants/{id} until GONE; do not recreate yet",
                    "id": tenant_id,
                }
            ),
            409,
        )
    if existing and existing.get("status") == "SUSPENDED":
        return jsonify({"error": "suspended", "message": "POST /tenants/{id}/resume"}), 409

    store.upsert(tenant_id, desired_status="ACTIVE", status="PROVISIONING", tier=tier, error=None)

    def _fn() -> None:
        provision(
            store,
            _tofu_dir,
            tenant_id,
            tier=tier,
            ensure_infra_flag=ensure_infra,
            ensure_identity_flag=ensure_identity and not ensure_infra,
            my_ip=os.environ.get("MY_IP"),
        )

    body_out, code = _start_job(tenant_id, "PROVISIONING", _fn)
    return jsonify(body_out), code


@app.post("/tenants/<tenant_id>/suspend")
def suspend(tenant_id: str):
    tenant_id = validate_tenant_id(tenant_id)
    try:
        item = suspend_tenant(store, tenant_id)
        return jsonify(_public(item)), 200
    except OnboardError as exc:
        return jsonify({"error": "suspend_failed", "message": str(exc)}), 400


@app.post("/tenants/<tenant_id>/resume")
def resume(tenant_id: str):
    tenant_id = validate_tenant_id(tenant_id)
    item = store.get(tenant_id)
    if not item:
        return jsonify({"error": "not_found", "id": tenant_id}), 404
    if item.get("status") == "ACTIVE":
        return jsonify(_public(item)), 200
    if item.get("status") != "SUSPENDED":
        return (
            jsonify({"error": "invalid_state", "message": f"status={item.get('status')}"}),
            409,
        )

    def _fn() -> None:
        try:
            resume_tenant(store, _tofu_dir, tenant_id)
        except ControlPlaneError as exc:
            store.upsert(tenant_id, status="FAILED", desired_status="ACTIVE", error=str(exc))

    body_out, code = _start_job(tenant_id, "SUSPENDED", _fn)
    return jsonify(body_out), code


@app.delete("/tenants/<tenant_id>")
def remove(tenant_id: str):
    tenant_id = validate_tenant_id(tenant_id)
    item = store.get(tenant_id)
    if not item:
        # Still try k8s cleanup for orphan namespaces
        store.upsert(tenant_id, desired_status="GONE", status="DELETING", error=None)

    def _fn() -> None:
        try:
            delete_tenant(store, _tofu_dir, tenant_id)
        except Exception as exc:  # noqa: BLE001
            if store.get(tenant_id):
                store.upsert(tenant_id, status="DELETE_FAILED", desired_status="GONE", error=str(exc))

    if item and item.get("status") == "DELETING":
        with _provision_lock:
            if tenant_id in _inflight:
                return jsonify(_public(item)), 202

    store.upsert(tenant_id, desired_status="GONE", status="DELETING", error=None)
    body_out, code = _start_job(tenant_id, "DELETING", _fn)
    return jsonify(body_out), code


@app.post("/reconcile")
def reconcile():
    return jsonify(reconcile_all(store, _tofu_dir))


@app.post("/tenants/<tenant_id>/reconcile")
def reconcile_tenant(tenant_id: str):
    tenant_id = validate_tenant_id(tenant_id)
    return jsonify(reconcile_one(store, _tofu_dir, tenant_id))


def main() -> None:
    discover_active(store, _tofu_dir)
    host = os.environ.get("CP_HOST", "127.0.0.1")
    port = int(os.environ.get("CP_PORT", "8088"))
    try:
        assert_bind_safety(host)
    except BindUnsafeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    token = configured_token()
    auth_note = "Bearer token required" if token else "loopback, no API token (lab)"
    print(f"tenant control plane on http://{host}:{port} ({auth_note}; tofu_dir={_tofu_dir})")
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()
