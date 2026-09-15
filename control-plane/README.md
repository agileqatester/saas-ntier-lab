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
control-plane/.venv/bin/python control-plane/cli.py delete g       # ns + SM + IRSA + DROP ROLE
control-plane/.venv/bin/python control-plane/cli.py get g
```

`helm/test-app/onboard_tenant.py` is **deprecated** (prints a warning; still calls the shared onboard library).

## HTTP API

```bash
control-plane/.venv/bin/python control-plane/app.py   # :8088

curl -sS -X POST http://127.0.0.1:8088/tenants \
  -H 'Content-Type: application/json' -d '{"id":"g","tier":"standard"}'
curl -sS http://127.0.0.1:8088/tenants/g
curl -sS -X POST http://127.0.0.1:8088/tenants/g/suspend
curl -sS -X POST http://127.0.0.1:8088/tenants/g/resume
curl -sS -X DELETE http://127.0.0.1:8088/tenants/g
```

## How it works

1. **Identity** (`aws_identity.py`): create/delete `name_prefix/rds/tenant-<id>` secret and `name_prefix-tenant-<id>` IRSA role (OIDC from tofu outputs).
2. **Migrate refresh**: re-run the platform tenant (`a`) migrate Job so Postgres gets `CREATE ROLE` + RLS policy for the new secret map.
3. **Onboard** (`onboard_tenant.onboard`): namespace, NetworkPolicy (public subnet CIDRs), ResourceQuota, Helm ClusterIP + Ingress (`alb` class, shared `group.name`).
4. **Lifecycle** (`lifecycle.py` + `pg_admin.py`): suspend/resume; delete drops PG role via Job in `tenant-a` (migrator IRSA), then Helm/ns/AWS identity.
5. **Registry**: `control-plane/data/tenants.json` (gitignored). Reloaded on read so CLI and API stay in sync.

Legacy escape hatch: `POST` with `"ensure_infra": true` still edits tfvars + `tofu apply` (`infra.py`).

## Layout

```
control-plane/
  app.py            # Flask API
  cli.py            # CLI entry
  provisioner.py    # create orchestration
  lifecycle.py      # suspend / resume / delete
  aws_identity.py   # SM + IRSA
  pg_admin.py       # DROP ROLE Job
  adopt.py          # adopt existing AWS identity
  store.py          # tenants.json registry
  infra.py          # legacy tofu ensure_infra
  requirements.txt
  data/             # gitignored runtime state
```
