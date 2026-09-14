# Tenant Isolation QA

Contract: [contracts/tenant_contract.md](contracts/tenant_contract.md)

Tests assert **isolation behavior** over ALB path URLs (`/tenant-a/...`). They do **not** assert NodePort numbers — that stays a lab ingress detail until the control plane moves to shared Ingress/IP targets.

## Setup

```bash
python3 -m venv .venv-tests
source .venv-tests/bin/activate
pip install -r tests/requirements.txt

export TENANT_BASE_URL="$(tofu -chdir=env/dev/workload output -raw alb_url)"
# kubectl must already point at the cluster (update-kubeconfig)
```

## Run

```bash
cd tests
pytest -v
# or
pytest -v -m smoke
pytest -v isolation/test_database.py
```

## Permanent tenants

Configured in `config/tenants.yaml` (`a` / `b`). Do not generate fresh tenants per test.
