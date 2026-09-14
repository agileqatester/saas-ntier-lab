# Tenant contract (isolation QA)

The control plane may change **how** a tenant is created. It may **not** change what a correctly isolated **ACTIVE** tenant means.

These invariants are what `tests/` encodes. Prefer behavior over Kubernetes/Terraform object names.

## ACTIVE tenant — definition of done

A tenant id `T` is ACTIVE when:

- Namespace `tenant-T` exists and is labeled for the tenant
- Workload is Ready (Deployment/pods)
- Service exists and is reachable on the **product edge path** `/tenant-T/*`
- ServiceAccount + IRSA can read **only** that tenant’s secret
- DB role works; RLS is enabled + forced on tenant tables
- Tenant can read/write **own** rows only
- Tenant cannot read/write another tenant’s rows (API + DB)
- Missing `app.tenant_id` yields **no** tenant rows (fail closed)
- East-west: cannot reach another tenant’s Service
- ResourceQuota bounds that tenant’s compute (noisy-neighbor)

## Not part of the contract (implementation details)

| Today (lab) | Why it is *not* a contract |
|-------------|----------------------------|
| NodePort `30080 + index` | ALB instance-target hook only; does not scale to ~100 tenants |
| `onboard_tenant.py` + `var.tenant_ids` OpenTofu apply | Manual/scripted bootstrap; control plane replaces this path |
| Exact ResourceQuota object name | Quota **effect** matters |
| Exact NetworkPolicy YAML shape | **Cannot connect** matters |

## Control plane scaling notes (future)

NodePort-per-tenant + ALB listener rule-per-tenant + OpenTofu `for_each` IRSA **will not sustain ~100 tenants** on this pattern:

- NodePort range / SG surface / listener rule limits
- Slow state & applies; sequential Helm onboard
- Pod density on a single small node

Target direction when expanding the control plane:

1. Keep **pooled** compute + shared Postgres + RLS (this lab’s model)
2. Replace product ingress with **shared ALB/Ingress (IP targets or AWS LB Controller)** — path or host routing, **no dedicated NodePort per tenant**
3. Onboard via API/reconciler (create namespace, Helm/Operator, IAM/secret binding) instead of editing `tenant_ids` + script
4. Same QA suite must still pass (fixtures use `base_url` + `path_prefix`, not ports)

## Lifecycle (tests later)

`CREATE → PROVISIONING → ACTIVE → SUSPEND/RESUME → DELETE` is validated **after** the control plane exists, using this same contract for ACTIVE.
