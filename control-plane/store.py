"""In-memory + file-backed tenant registry for the control-plane MVP."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

STATUSES = ("PROVISIONING", "ACTIVE", "SUSPENDED", "DELETING", "FAILED")


class TenantStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._tenants: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._tenants = {}
            return
        raw = json.loads(self._path.read_text())
        self._tenants = {str(k): v for k, v in raw.get("tenants", {}).items()}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"tenants": self._tenants}
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def get(self, tenant_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._load()  # pick up CLI / other process writes
            item = self._tenants.get(tenant_id)
            return dict(item) if item else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            self._load()
            return [dict(v) for _, v in sorted(self._tenants.items())]

    def upsert(self, tenant_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            current = dict(self._tenants.get(tenant_id) or {"id": tenant_id})
            current.update(fields)
            current["id"] = tenant_id
            current["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if "created_at" not in current:
                current["created_at"] = current["updated_at"]
            self._tenants[tenant_id] = current
            self._save()
            return dict(current)

    def delete(self, tenant_id: str) -> bool:
        with self._lock:
            if tenant_id not in self._tenants:
                return False
            del self._tenants[tenant_id]
            self._save()
            return True
