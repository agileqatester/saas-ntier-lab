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
- Lab user `X-Lab-User` may access only mapped tenants (401 missing/unknown, 403 cross-tenant); header is **not** a Postgres tenant switch
- East-west: cannot reach another tenant’s Service
- Tenant SA cannot create Ingress; wrong `group.name` / class / path is admission-denied
- Egress default-deny except DNS, Postgres, same-namespace, and lab HTTPS
- ResourceQuota bounds that tenant’s compute (noisy-neighbor)

**Control-plane registry `ACTIVE` vs this contract:** the reconciler marks registry ACTIVE only after observed infrastructure is present (ns, Ready deploy, Ingress, Service, NetworkPolicy, ResourceQuota, IRSA-annotated SA) **and** `validate_active_contract()` passes (registry identity pointers for CP-owned tenants). That is a cheap fail-closed gate — not a substitute for this suite. Functional isolation (RLS, cross-tenant, egress deny, …) is proven by `tests/`, not by `observe.py`.

## Not part of the contract (implementation details)

| Lab detail | Why it is *not* a contract |
|------------|----------------------------|
| NodePort `30080 + index` (legacy `ingress_mode=nodeport`) | Replaced by ClusterIP + shared Ingress in Phase A |
| OpenTofu `for_each` on `tenant_ids` for SM/IRSA | Control plane owns identity (`manage_tenant_identity=false`) |
| Exact ResourceQuota object name | Quota **effect** matters |
| Exact NetworkPolicy YAML shape | **Cannot connect** matters |

## Control plane (current lab)

Implemented under [`control-plane/`](../../control-plane/). Design:
[`docs/saas/TENANT_CONTROL_PLANE.md`](../../docs/saas/TENANT_CONTROL_PLANE.md).
Verification log: [`docs/saas/VERIFICATION.md`](../../docs/saas/VERIFICATION.md).

Scaling notes that still apply for ~100 tenants: cells / pod density, not
NodePort-per-tenant. Host-based routing is Phase B.

Lifecycle (`CREATE → ACTIVE → SUSPEND/RESUME → DELETE`) is an automated
Control Plane contract ([`control_plane_contract.md`](./control_plane_contract.md)).
ACTIVE isolation stays this contract’s pytest suite.
