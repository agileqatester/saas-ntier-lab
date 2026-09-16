# Tenant Control Plane

Local Flask API + CLI that own **per-tenant identity and lifecycle** on the shared
EKS/RDS lab. Platform networking/compute stays in OpenTofu
(`manage_tenant_identity=false`).

Design & verification: [`docs/saas/TENANT_CONTROL_PLANE.md`](../docs/saas/TENANT_CONTROL_PLANE.md),
[`docs/saas/VERIFICATION.md`](../docs/saas/VERIFICATION.md).

## Setup

```bash
python3 -m venv control-plane/.venv
control-plane/.venv/bin/pip install -r control-plane/requirements.txt
export TOFU_DIR=$PWD/env/dev/workload
export MY_IP="$(curl -s https://checkip.amazonaws.com)/32"
# kubectl must already target the cluster
```

Use **`control-plane/.venv/bin/python`** — system `python3` will miss `boto3`.

## CLI (preferred)

```bash
control-plane/.venv/bin/python control-plane/cli.py adopt          # one-time
control-plane/.venv/bin/python control-plane/cli.py create g
control-plane/.venv/bin/python control-plane/cli.py list
control-plane/.venv/bin/python control-plane/cli.py suspend g
control-plane/.venv/bin/python control-plane/cli.py resume g
control-plane/.venv/bin/python control-plane/cli.py delete g       # retry-safe; DELETE_FAILED if DB revoke fails
control-plane/.venv/bin/python control-plane/cli.py reconcile g    # desired vs actual; does not auto-ACTIVE namespaces
control-plane/.venv/bin/python control-plane/cli.py get g
```

`helm/test-app/onboard_tenant.py` is **deprecated** (prints a warning; still calls the shared onboard library).

## HTTP API

Lab default: `CP_HOST=127.0.0.1` — no token. **Non-loopback bind is refused** unless
`CP_API_TOKEN` is set. That is a static Bearer token, not OIDC.

```bash
control-plane/.venv/bin/python control-plane/app.py   # :8088 on 127.0.0.1

# Non-loopback (still a lab token, not production IdP):
# export CP_HOST=0.0.0.0 CP_API_TOKEN='…'
# curl -H "Authorization: Bearer $CP_API_TOKEN" …

curl -sS -X POST http://127.0.0.1:8088/tenants \
  -H 'Content-Type: application/json' -d '{"id":"g","tier":"standard"}'
curl -sS http://127.0.0.1:8088/tenants/g
curl -sS -X POST http://127.0.0.1:8088/tenants/g/suspend
curl -sS -X POST http://127.0.0.1:8088/tenants/g/resume
curl -sS -X DELETE http://127.0.0.1:8088/tenants/g
curl -sS -X POST http://127.0.0.1:8088/tenants/g/reconcile
# DELETE is fail-closed: if DROP ROLE fails, status is DELETE_FAILED — retry delete.
```

## How it works

1. **Identity** (`aws_identity.py`): create/delete `name_prefix/rds/tenant-<id>` secret and `name_prefix-tenant-<id>` IRSA role (OIDC from tofu outputs).
2. **Migrate refresh**: re-run the platform tenant (`a`) migrate Job so Postgres gets `CREATE ROLE` + RLS policy for the new secret map.
3. **Onboard** (`onboard_tenant.onboard`): namespace, NetworkPolicy (ingress + default-deny egress), ResourceQuota, Helm ClusterIP + Ingress (`alb` class, shared `group.name`), platform-guardrails VAP.
4. **Lifecycle** (`lifecycle.py` + `pg_admin.py`): suspend/resume; delete disables access, revokes the Postgres role (`NOLOGIN` + password rotate + `DROP ROLE` with retries), then Helm/ns, then IRSA, then the secret. DB revoke failure → `DELETE_FAILED` (retryable); Kubernetes/AWS identity are not removed while the role still exists.
5. **Registry**: `control-plane/data/tenants.db` (SQLite WAL, gitignored). CLI and Flask share the same file with transactions and optimistic `version` concurrency. Legacy `tenants.json` is imported once if the DB is empty. Multi-instance production should move this table to DynamoDB or PostgreSQL.
6. **Reconcile**: commands set `desired_status` (`ACTIVE` / `SUSPENDED` / `GONE`). `cli.py reconcile` (or `POST /reconcile`) compares observed K8s against that desired state. A namespace existing is **not** ACTIVE.

Legacy escape hatch: `POST` with `"ensure_infra": true` still edits tfvars + `tofu apply` (`infra.py`).

Lab secret teardown uses `ForceDeleteWithoutRecovery`. Set `CP_SECRET_RECOVERY_DAYS=7` (7–30) for a recovery window. That still does not revoke a leaked DB password — the role does.

## Layout

```
control-plane/
  app.py            # Flask API (loopback by default; CP_API_TOKEN if not)
  cli.py            # CLI entry
  safety.py         # bind guard + Bearer check + secret recovery window
  provisioner.py    # create orchestration
  lifecycle.py      # suspend / resume / delete (fail-closed)
  aws_identity.py   # SM + IRSA
  pg_admin.py       # revoke/DROP ROLE Job
  errors.py         # typed errors + with_retry (AWS/K8s throttling)
  ids.py            # validate_tenant_id() — API, CLI, provisioner, lifecycle, IAM
  observe.py        # actual namespace/deploy/ingress (does not invent ACTIVE)
  reconcile.py      # desired vs observed
  adopt.py          # adopt existing AWS identity
  store.py          # SQLite tenants.db (WAL + version)
  infra.py          # legacy tofu ensure_infra
  requirements.txt
  data/             # gitignored runtime state (tenants.db; optional tenants.json import)
```
