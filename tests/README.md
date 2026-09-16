# Tenant Isolation QA

Contract: [contracts/tenant_contract.md](contracts/tenant_contract.md)  
Control plane design: [docs/saas/TENANT_CONTROL_PLANE.md](../docs/saas/TENANT_CONTROL_PLANE.md)  
What we already ran on the live stack: [docs/saas/VERIFICATION.md](../docs/saas/VERIFICATION.md)

Tests assert **isolation behavior** over ALB path URLs (`/tenant-a/...`). They do
**not** assert NodePort numbers — the lab edge is shared Ingress
(`ingress_mode=alb_controller`).

Authentication is intentionally out of scope. Product routes require simulated
tenant authorization via `X-Lab-User` (see `labAuth.users` in the Helm chart).
`/health` stays unauthenticated so probes keep working. PostgreSQL session
`tenant_id` still comes from the pod, never from that header.

## Setup

```bash
python3 -m venv .venv-tests
source .venv-tests/bin/activate
pip install -r tests/requirements.txt

export TENANT_BASE_URL="$(cat ../env/dev/workload/.alb_url)"
# fallback after tofu refresh:
# export TENANT_BASE_URL="$(tofu -chdir=../env/dev/workload output -raw alb_url)"
# kubectl must already point at the cluster
```

## Run

```bash
cd tests
pytest -v -m unit
pytest -v
# or
pytest -v -m smoke
pytest -v isolation/test_authorization.py
pytest -v isolation/test_database.py
pytest -v isolation/test_network.py isolation/test_iam.py isolation/test_compute.py isolation/test_ingress_guardrails.py
```

Live isolation tests need a Helm/control-plane re-onboard so tenants pick up egress NetworkPolicy, tenant RBAC, and `platform-guardrails` VAP (plus lab-user auth).

**Last recorded result (shared Ingress edge):** **23 passed** (isolation + smoke, before lab-user authorization). Re-run after Helm upgrade; expect additional unit + authorization tests.

## Suite map

| Area | Files | Asserts |
|------|-------|---------|
| Unit | `unit/test_lab_auth.py`, `unit/test_cp_*.py`, `unit/test_sqlite_store.py`, `unit/test_tenant_id.py`, `unit/test_reconcile_plan.py`, `unit/test_platform_guardrails.py` | authz map, CP bind/delete invariants, SQLite registry, shared tenant-id, reconciler plan, VAP + egress templates |
| CP contract | `control_plane/test_contract.py` | CREATE/SUSPEND/RESUME/DELETE + failure injection (fakes; no cluster) |
| Smoke | `smoke/test_tenants.py` | ns, Ready, `/health`, DB |
| Authz | `isolation/test_authorization.py` | user→own tenant OK; cross-tenant 403; header ≠ DB tenant |
| Data | `isolation/test_database.py` | RLS own/spoof/missing context |
| IAM | `isolation/test_iam.py` | secret read own-only |
| Network | `isolation/test_network.py` | east-west deny; egress :80 deny |
| Edge | `isolation/test_ingress_guardrails.py` | tenant SA cannot create Ingress; foreign `group.name` / path denied |
| Compute | `isolation/test_compute.py` | ResourceQuota / noisy neighbor |

## Permanent tenants

Configured in `config/tenants.yaml` (`a` / `b`). Do not generate fresh tenants per test.
Control-plane-created tenants (`f`, `g`, …) still need a live cluster for CLI/API
verification ([VERIFICATION.md](../docs/saas/VERIFICATION.md)). The **lifecycle
state machine** is automated without AWS: `pytest -m unit` includes
[`control_plane/test_contract.py`](control_plane/test_contract.py)
([contract](contracts/control_plane_contract.md)).
