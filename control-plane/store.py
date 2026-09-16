"""SQLite tenant registry — transactions, WAL, optimistic concurrency.

Lab: one file, CLI + Flask can share it safely. Multi-instance production
should move this table to DynamoDB or PostgreSQL.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from errors import ConflictError, ValidationError
from ids import validate_tenant_id

STATUSES = (
    "PROVISIONING",
    "ACTIVE",
    "SUSPENDED",
    "DELETING",
    "DELETE_FAILED",
    "FAILED",
    "DRIFT",
)

DESIRED_STATUSES = ("ACTIVE", "SUSPENDED", "GONE")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    desired_status TEXT NOT NULL,
    status TEXT NOT NULL,
    tier TEXT,
    endpoint TEXT,
    path_prefix TEXT,
    owned_by TEXT,
    secret_name TEXT,
    irsa_role_arn TEXT,
    error TEXT,
    delete_step TEXT,
    observed_json TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_FIELDS = (
    "id",
    "desired_status",
    "status",
    "tier",
    "endpoint",
    "path_prefix",
    "owned_by",
    "secret_name",
    "irsa_role_arn",
    "error",
    "delete_step",
    "observed_json",
    "version",
    "created_at",
    "updated_at",
)


def _utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    item = {k: row[k] for k in row.keys()}
    item["version"] = int(item["version"])
    return item


class TenantStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        self._import_legacy_json()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _import_legacy_json(self) -> None:
        legacy = self._path.parent / "tenants.json"
        if not legacy.exists():
            return
        with self._connect() as conn:
            n = conn.execute("SELECT COUNT(*) AS c FROM tenants").fetchone()["c"]
            if n:
                return
            try:
                raw = json.loads(legacy.read_text())
            except json.JSONDecodeError:
                return
            now = _utcnow()
            for tid, meta in (raw.get("tenants") or {}).items():
                try:
                    tid = validate_tenant_id(str(tid))
                except ValidationError:
                    continue
                status = str(meta.get("status") or "ACTIVE")
                desired = "GONE" if status in ("DELETING", "DELETE_FAILED") else (
                    "SUSPENDED" if status == "SUSPENDED" else "ACTIVE"
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO tenants (
                        id, desired_status, status, tier, endpoint, path_prefix,
                        owned_by, secret_name, irsa_role_arn, error, delete_step,
                        observed_json, version, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        tid,
                        desired,
                        status,
                        meta.get("tier") or "standard",
                        meta.get("endpoint"),
                        meta.get("path_prefix"),
                        meta.get("owned_by"),
                        meta.get("secret_name"),
                        meta.get("irsa_role_arn"),
                        meta.get("error"),
                        meta.get("delete_step"),
                        None,
                        1,
                        meta.get("created_at") or now,
                        meta.get("updated_at") or now,
                    ),
                )

    def get(self, tenant_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
            return _row_to_item(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM tenants ORDER BY id").fetchall()
            return [_row_to_item(r) for r in rows]

    def upsert(
        self,
        tenant_id: str,
        *,
        expected_version: int | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        tenant_id = validate_tenant_id(tenant_id)
        now = _utcnow()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
            if row is not None:
                if expected_version is not None and int(row["version"]) != expected_version:
                    raise ConflictError(
                        f"tenant {tenant_id} version conflict: "
                        f"have {row['version']}, expected {expected_version}"
                    )
                current = _row_to_item(row)
                current.update(fields)
                current["id"] = tenant_id
                current["updated_at"] = now
                current["version"] = int(current["version"]) + 1
                if current.get("desired_status") not in DESIRED_STATUSES:
                    raise ValidationError(
                        f"invalid desired_status {current.get('desired_status')!r}; "
                        f"must be one of {DESIRED_STATUSES}"
                    )
                conn.execute(
                    """
                    UPDATE tenants SET
                        desired_status=?, status=?, tier=?, endpoint=?, path_prefix=?,
                        owned_by=?, secret_name=?, irsa_role_arn=?, error=?, delete_step=?,
                        observed_json=?, version=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        current.get("desired_status"),
                        current.get("status"),
                        current.get("tier"),
                        current.get("endpoint"),
                        current.get("path_prefix"),
                        current.get("owned_by"),
                        current.get("secret_name"),
                        current.get("irsa_role_arn"),
                        current.get("error"),
                        current.get("delete_step"),
                        current.get("observed_json"),
                        current["version"],
                        current["updated_at"],
                        tenant_id,
                    ),
                )
                return current

            status = fields.get("status") or "PROVISIONING"
            desired = fields.get("desired_status")
            if desired is None:
                # Infer only when omitted — never silently rewrite a bad value.
                if status == "SUSPENDED":
                    desired = "SUSPENDED"
                elif status in ("DELETING", "DELETE_FAILED"):
                    desired = "GONE"
                else:
                    desired = "ACTIVE"
            elif desired not in DESIRED_STATUSES:
                raise ValidationError(
                    f"invalid desired_status {desired!r}; must be one of {DESIRED_STATUSES}"
                )
            created = fields.get("created_at") or now
            item = {
                "id": tenant_id,
                "desired_status": desired,
                "status": status,
                "tier": fields.get("tier") or "standard",
                "endpoint": fields.get("endpoint"),
                "path_prefix": fields.get("path_prefix"),
                "owned_by": fields.get("owned_by"),
                "secret_name": fields.get("secret_name"),
                "irsa_role_arn": fields.get("irsa_role_arn"),
                "error": fields.get("error"),
                "delete_step": fields.get("delete_step"),
                "observed_json": fields.get("observed_json"),
                "version": 1,
                "created_at": created,
                "updated_at": now,
            }
            conn.execute(
                """
                INSERT INTO tenants (
                    id, desired_status, status, tier, endpoint, path_prefix,
                    owned_by, secret_name, irsa_role_arn, error, delete_step,
                    observed_json, version, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                tuple(item[k] for k in _FIELDS),
            )
            return item

    def delete(self, tenant_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
            return cur.rowcount > 0
