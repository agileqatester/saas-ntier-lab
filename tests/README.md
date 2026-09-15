# Tenant Isolation QA

Contract: [contracts/tenant_contract.md](contracts/tenant_contract.md)  
Control plane design: [docs/saas/TENANT_CONTROL_PLANE.md](../docs/saas/TENANT_CONTROL_PLANE.md)  
What we already ran on the live stack: [docs/saas/VERIFICATION.md](../docs/saas/VERIFICATION.md)

Tests assert **isolation behavior** over ALB path URLs (`/tenant-a/...`). They do
**not** assert NodePort numbers — the lab edge is shared Ingress
(`ingress_mode=alb_controller`).

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
pytest -v
# or
pytest -v -m smoke
pytest -v isolation/test_database.py
pytest -v isolation/test_network.py isolation/test_iam.py isolation/test_compute.py
```

**Last recorded result (shared Ingress edge):** **23 passed**.

## Suite map

| Area | Files | Asserts |
|------|-------|---------|
| Smoke | `smoke/test_tenants.py` | ns, Ready, `/health`, DB |
| Data | `isolation/test_database.py` | RLS own/spoof/missing context |
| IAM | `isolation/test_iam.py` | secret read own-only |
| Network | `isolation/test_network.py` | east-west deny |
| Compute | `isolation/test_compute.py` | ResourceQuota / noisy neighbor |

## Permanent tenants

Configured in `config/tenants.yaml` (`a` / `b`). Do not generate fresh tenants per test.
Control-plane-created tenants (`f`, `g`, …) are exercised via CLI/API (see VERIFICATION.md), not this fixture set.
