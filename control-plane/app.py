#!/usr/bin/env python3
"""Tenant Control Plane — create + lifecycle (suspend/resume/delete).

  control-plane/.venv/bin/python control-plane/app.py

  curl -sS -X POST http://127.0.0.1:8088/tenants -H 'Content-Type: application/json' -d '{"id":"f"}'
  curl -sS -X POST http://127.0.0.1:8088/tenants/f/suspend
  curl -sS -X POST http://127.0.0.1:8088/tenants/f/resume
  curl -sS -X DELETE http://127.0.0.1:8088/tenants/f
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from flask import Flask, jsonify, request

from lifecycle import delete_tenant, resume_tenant, suspend_tenant
from onboard_bridge import OnboardError
from provisioner import discover_active, provision
from store import TenantStore

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOFU_DIR = REPO_ROOT / "env" / "dev" / "workload"
DATA_DIR = Path(__file__).resolve().parent / "data"

TENANT_ID_RE = re.compile(r"^[a-z][a-z0-9]{0,15}$")

app = Flask(__name__)
store = TenantStore(DATA_DIR / "tenants.json")
_tofu_dir = Path(os.environ.get("TOFU_DIR", str(DEFAULT_TOFU_DIR))).resolve()
_provision_lock = threading.Lock()
_inflight: set[str] = set()


def _public(tenant: dict) -> dict:
    return {
        "id": tenant.get("id"),
        "status": tenant.get("status"),
        "tier": tenant.get("tier"),
        "endpoint": tenant.get("endpoint"),
        "path_prefix": tenant.get("path_prefix"),
        "owned_by": tenant.get("owned_by"),
        "secret_name": tenant.get("secret_name"),
        "error": tenant.get("error"),
        "created_at": tenant.get("created_at"),
        "updated_at": tenant.get("updated_at"),
    }


def _flag(body: dict, key: str, default: bool) -> bool:
    val = body.get(key, default)
    if isinstance(val, str):
        return val.lower() in ("1", "true", "yes")
    return bool(val)


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
    item = store.get(tenant_id)
    if not item:
        return jsonify({"error": "not_found", "id": tenant_id}), 404
    return jsonify(_public(item))


@app.post("/tenants")
def create_tenant():
    body = request.get_json(silent=True) or {}
    tenant_id = str(body.get("id", "")).strip()
    tier = str(body.get("tier") or "standard").strip() or "standard"
    ensure_identity = _flag(body, "ensure_identity", True)
    ensure_infra = _flag(body, "ensure_infra", False)

    if not TENANT_ID_RE.match(tenant_id):
        return (
            jsonify({"error": "invalid_id", "message": "id must match ^[a-z][a-z0-9]{0,15}$"}),
            400,
        )

    existing = store.get(tenant_id)
    if existing and existing.get("status") == "ACTIVE":
        return jsonify(_public(existing)), 200
    if existing and existing.get("status") in ("PROVISIONING", "DELETING"):
        return jsonify(_public(existing)), 202
    if existing and existing.get("status") == "SUSPENDED":
        return jsonify({"error": "suspended", "message": "POST /tenants/{id}/resume"}), 409

    store.upsert(tenant_id, status="PROVISIONING", tier=tier, error=None)

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
    try:
        item = suspend_tenant(store, tenant_id)
        return jsonify(_public(item)), 200
    except OnboardError as exc:
        return jsonify({"error": "suspend_failed", "message": str(exc)}), 400


@app.post("/tenants/<tenant_id>/resume")
def resume(tenant_id: str):
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
        except Exception as exc:  # noqa: BLE001
            store.upsert(tenant_id, status="FAILED", error=str(exc))

    body_out, code = _start_job(tenant_id, "SUSPENDED", _fn)
    return jsonify(body_out), code


@app.delete("/tenants/<tenant_id>")
def remove(tenant_id: str):
    item = store.get(tenant_id)
    if not item:
        # Still try k8s cleanup for orphan namespaces
        store.upsert(tenant_id, status="DELETING", error=None)

    def _fn() -> None:
        try:
            delete_tenant(store, _tofu_dir, tenant_id)
        except Exception as exc:  # noqa: BLE001
            if store.get(tenant_id):
                store.upsert(tenant_id, status="FAILED", error=str(exc))

    if item and item.get("status") == "DELETING":
        return jsonify(_public(item)), 202

    store.upsert(tenant_id, status="DELETING", error=None)
    body_out, code = _start_job(tenant_id, "DELETING", _fn)
    return jsonify(body_out), code


def main() -> None:
    discover_active(store, _tofu_dir)
    host = os.environ.get("CP_HOST", "127.0.0.1")
    port = int(os.environ.get("CP_PORT", "8088"))
    print(f"tenant control plane on http://{host}:{port} (tofu_dir={_tofu_dir})")
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()
