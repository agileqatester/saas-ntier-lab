# Tenant Control Plane

**Status:** implemented and verified in the Dev lab (2026-09).  
**Code:** [`control-plane/`](../../control-plane/) · **Isolation contract:** [`tests/contracts/tenant_contract.md`](../../tests/contracts/tenant_contract.md) · **CP contract:** [`tests/contracts/control_plane_contract.md`](../../tests/contracts/control_plane_contract.md) · **Verification log:** [`VERIFICATION.md`](./VERIFICATION.md)

The control plane may change **how** a tenant is created. It may **not** change what a correctly isolated **ACTIVE** tenant means.

---

## Goals (lab)

1. Onboard / suspend / resume / delete tenants without editing `tenant_ids` + hand-running OpenTofu for identity.
2. Scale toward many pooled tenants without NodePort-per-tenant / ALB-rule-per-tenant.
3. Keep isolation: **lab user authorization + shared EKS + shared Postgres + RLS + per-tenant IRSA + NetworkPolicy + ResourceQuota**.

Non-goals (later): multi-region, silo VPCs, AI plane, HTTPS/PrivateLink, real authentication (OIDC/OAuth2).

---

## What shipped

| Area | Implementation |
|------|----------------|
| Product edge | Shared ALB Ingress group + `ValidatingAdmissionPolicy` (`helm/platform-guardrails`) so tenants cannot pick another `group.name` / class / path |
| Identity | Control plane creates SM secret + IRSA (`manage_tenant_identity=false`); OpenTofu owns VPC/EKS/RDS/LBC/migrator |
| Onboard | Same Helm chart as before; library in `helm/test-app/onboard_tenant.py`, driven by CP |
| CLI / API | `control-plane/cli.py` (preferred) and local Flask API on `127.0.0.1:8088` (non-loopback requires `CP_API_TOKEN`) |
| Lifecycle | suspend (scale 0 + drop Ingress), resume (re-onboard path), delete (disable access → revoke DB role → k8s → IRSA → secret; `DELETE_FAILED` if DB revoke fails) |
| Bootstrap | `a`–`e` adopted to `owned_by: control_plane` (one-time `adopt` + tofu `state rm`) |

---

## Architecture

```text
                    ┌─────────────────────────────┐
  laptop / CI       │  control-plane (operator)   │
                    │  127.0.0.1 or Bearer token  │
                    │  registry: data/tenants.db  │
                    │  (SQLite WAL + version)     │
                    └──────────┬──────────────────┘
           ensure_identity     │     onboard / lifecycle
           (boto3 SM+IAM)      │     (kubectl/helm)
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Application plane                                            │
│  AWS LBC → one internet-facing ALB                           │
│  Ingress group → /tenant-<id> → ClusterIP → pod              │
│  VAP: group.name + alb class + path scoped to namespace      │
│  NetPol: deny ingress east-west; deny egress except DNS/PG/443│
│  App: X-Lab-User map (authn out of scope) then TENANT_ID     │
│  Postgres: FORCE RLS + role tenant_<id>                      │
│  Platform: VPC, EKS (t4g.medium), RDS, NAT (OpenTofu)        │
└──────────────────────────────────────────────────────────────┘
```

### Module map (`control-plane/`)

| File | Role |
|------|------|
| `app.py` | HTTP API: create, get, list, suspend, resume, delete, reconcile. Loopback by default; non-loopback requires `CP_API_TOKEN` |
| `cli.py` | Same operations from the shell (use `.venv`). Tenant ids go through `validate_tenant_id()` |
| `ids.py` | One tenant-id regex used by API, CLI, provisioner, lifecycle, AWS identity |
| `errors.py` | `ValidationError`, `ConflictError`, retryable AWS/K8s errors, `with_retry` |
| `safety.py` | Bind guard, Bearer check, secret recovery-window setting |
| `provisioner.py` | Orchestrates identity + migrate refresh + Helm onboard; does not invent ACTIVE from a namespace |
| `aws_identity.py` | Create/delete SM secret + IRSA role (IAM then secret; lab force-delete); AWS throttling is retried |
| `lifecycle.py` | Suspend / resume / fail-closed delete |
| `observe.py` | Actual namespace / deploy / Ingress (namespace-only is not ACTIVE) |
| `reconcile.py` | Desired vs observed; `POST /reconcile` and `cli.py reconcile` |
| `pg_admin.py` | Job: `ALTER ROLE NOLOGIN` + password rotate + `DROP ROLE` |
| `adopt.py` | Mark existing AWS identity as CP-owned |
| `store.py` | SQLite registry (`data/tenants.db`); imports legacy `tenants.json` once |
| `infra.py` | Legacy `ensure_infra` (tfvars + tofu apply) |

OpenTofu still supplies: `rds_host`, `migrator_irsa_role_arn`, `oidc_provider_*`, `public_subnet_cidrs`, `private_subnet_cidrs`, `alb_logs_bucket`, `platform_tenant_id`, `ingress_mode`.

**Shared `group.name`:** the control plane installs `helm/platform-guardrails` (ValidatingAdmissionPolicy) before tenant Ingress. Tenant ServiceAccounts have no Ingress RBAC. Only the CP Helm release should create `/tenant-<id>` on the shared ALB.

Commands set **desired** status. The reconciler makes **actual** match desired after crashes, timeouts, and partial provision:

```text
Registry (SQLite)
   ↓
desired_status: ACTIVE | SUSPENDED | GONE
   ↓
Reconciler
   ↓
K8s + IAM + Secrets + DB
   ↓
Observed (namespace + Ready deploy + replicas + Ingress)
```

A `tenant-*` namespace with no Ready workload and no Ingress is **drift**, not ACTIVE.

### Provisioning flow

```text
POST /tenants { "id": "g" }   or   cli.py create g
        │
        ▼
   PROVISIONING
        ├─ SM secret + IRSA (boto3)
        ├─ Re-run migrate Job on platform tenant (a) with full secret map
        ├─ Namespace + NetworkPolicy + ResourceQuota + Helm (ClusterIP + Ingress)
        └─ Wait Ingress hostname → write env/dev/workload/.alb_url
        ▼
   ACTIVE
```

### Lifecycle

| Action | Effect |
|--------|--------|
| suspend | `replicas=0`, delete Ingress → `SUSPENDED` (data kept) |
| resume | Re-apply Helm/Ingress, scale 1 → `ACTIVE` |
| delete | See deletion state machine below |

```text
DELETING
   │
   ├── disable application access (scale 0 + drop Ingress)
   │
   ├── revoke DB role   ← the actual authority
   │      ALTER ROLE NOLOGIN
   │      ALTER ROLE PASSWORD <random>
   │      DROP ROLE (retry)
   │      └── failure → DELETE_FAILED (do not delete k8s / IAM / secret)
   │
   ├── delete Kubernetes (helm + namespace)
   │
   ├── delete IRSA
   │
   ├── delete secret (lab: ForceDeleteWithoutRecovery;
   │                  set CP_SECRET_RECOVERY_DAYS=7..30 for a recovery window)
   │
   ▼
GONE (registry row removed)

Retry: DELETE /tenants/{id} or cli.py delete from DELETING / DELETE_FAILED.
Steps are idempotent (role_absent, ns gone, IAM/secret already deleted).
```

Deleting the Secrets Manager object does **not** invalidate a password that already leaked. The Postgres role does. Lab force-delete is intentional; production should disable the role, remove the workload and IAM, then delete the secret with a recovery window.

This HTTP API is still an **operator tool**, not a production control plane. Future service:

```text
Admin UI/API
     │
     ▼
OIDC / Cognito / IAM Identity Center
     │
     ▼
Control Plane   (RBAC: platform-admin / tenant-admin / read-only)
```

---

## API / CLI

| Method | Path / command | Effect |
|--------|----------------|--------|
| `POST` | `/tenants` | Create → desired ACTIVE |
| `GET` | `/tenants`, `/tenants/{id}` | List / status |
| `POST` | `/tenants/{id}/suspend` | Desired SUSPENDED |
| `POST` | `/tenants/{id}/resume` | Desired ACTIVE |
| `DELETE` | `/tenants/{id}` | Desired GONE (retry from `DELETE_FAILED`) |
| `POST` | `/reconcile`, `/tenants/{id}/reconcile` | Make actual match desired |
| CLI | `cli.py create\|suspend\|resume\|delete\|reconcile\|list\|adopt` | Same |

Run details: [`control-plane/README.md`](../../control-plane/README.md).

---

## Workload knobs (`env/dev/workload`)

```hcl
ingress_mode             = "alb_controller"  # or "nodeport" (legacy)
eks_node_instance_type   = "t4g.medium"      # LBC + several tenants
manage_tenant_identity   = false             # CP owns SM/IRSA
platform_tenant_id       = "a"               # migrate Job namespace
tenant_ids               = []                # unused when manage_tenant_identity=false
```

ALB URL after onboard: `cat env/dev/workload/.alb_url` (also `tofu output -raw alb_url` after refresh).

---

## Tests & verification

Isolation suite: [`tests/`](../../tests/). Control Plane lifecycle contract (CREATE/SUSPEND/RESUME/DELETE + failure injection, no live cluster): [`tests/contracts/control_plane_contract.md`](../../tests/contracts/control_plane_contract.md). Live CLI exercises: [`VERIFICATION.md`](./VERIFICATION.md).

Acceptance rule: anything the CP provisions must keep [`tests/`](../../tests/) green for the isolation contract (fixtures still use tenants `a` / `b` over `TENANT_BASE_URL`). Product API calls need `X-Lab-User`; `/health` does not.

---

## What’s left (product, not lab blockers)

- HTTPS (ACM) + domain
- PrivateLink for corporate tenants
- Shrink NAT — interface VPC endpoints so tenant egress HTTPS is not `0.0.0.0/0` (today the lab allows :443 for pip + AWS APIs)
- Private-only EKS API (`endpoint_public_access=false`) when the operator path no longer needs a public kube-apiserver
- Run control plane as an in-cluster service with its own IRSA (today: laptop process + operator AWS creds)
- Multi-instance Control Plane: migrate `tenants.db` to DynamoDB or PostgreSQL (SQLite is the lab fit: transactions without another AWS service)
- Control-plane OIDC (Cognito / IAM Identity Center) + RBAC (`platform-admin`, `tenant-admin`, `read-only`). Today: loopback bind, or `CP_API_TOKEN` if you must listen off-loopback.
- Replace lab `X-Lab-User` with an external OIDC/OAuth2 identity provider for **tenant users** (authentication is out of scope here)
