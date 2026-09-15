# Tenant Control Plane

**Status:** implemented and verified in the Dev lab (2026-09).  
**Code:** [`control-plane/`](../../control-plane/) · **Contract:** [`tests/contracts/tenant_contract.md`](../../tests/contracts/tenant_contract.md) · **Verification log:** [`VERIFICATION.md`](./VERIFICATION.md)

The control plane may change **how** a tenant is created. It may **not** change what a correctly isolated **ACTIVE** tenant means.

---

## Goals (lab)

1. Onboard / suspend / resume / delete tenants without editing `tenant_ids` + hand-running OpenTofu for identity.
2. Scale toward many pooled tenants without NodePort-per-tenant / ALB-rule-per-tenant.
3. Keep isolation: **shared EKS + shared Postgres + RLS + per-tenant IRSA + NetworkPolicy + ResourceQuota**.

Non-goals (later): multi-region, silo VPCs, AI plane, HTTPS/PrivateLink.

---

## What shipped

| Area | Implementation |
|------|----------------|
| Product edge | `ingress_mode=alb_controller`: ClusterIP Services + shared ALB via AWS Load Balancer Controller (`group.name`) |
| Identity | Control plane creates SM secret + IRSA (`manage_tenant_identity=false`); OpenTofu owns VPC/EKS/RDS/LBC/migrator |
| Onboard | Same Helm chart as before; library in `helm/test-app/onboard_tenant.py`, driven by CP |
| Lifecycle | suspend (scale 0 + drop Ingress), resume (re-onboard path), delete (ns + SM + IRSA + `DROP ROLE`) |
| CLI / API | `control-plane/cli.py` (preferred) and local Flask API on `:8088` |
| Bootstrap | `a`–`e` adopted to `owned_by: control_plane` (one-time `adopt` + tofu `state rm`) |

---

## Architecture

```text
                    ┌─────────────────────────────┐
  laptop / CI       │  control-plane (Flask+CLI)  │
                    │  registry: data/tenants.json│
                    └──────────┬──────────────────┘
           ensure_identity     │     onboard / lifecycle
           (boto3 SM+IAM)      │     (kubectl/helm)
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Application plane                                            │
│  AWS LBC → one internet-facing ALB                           │
│  Ingress group → /tenant-<id> → ClusterIP → pod              │
│  Postgres: FORCE RLS + role tenant_<id>                      │
│  Platform: VPC, EKS (t4g.medium), RDS, NAT (OpenTofu)        │
└──────────────────────────────────────────────────────────────┘
```

### Module map (`control-plane/`)

| File | Role |
|------|------|
| `app.py` | HTTP API: create, get, list, suspend, resume, delete |
| `cli.py` | Same operations from the shell (use `.venv`) |
| `provisioner.py` | Orchestrates identity + migrate refresh + Helm onboard |
| `aws_identity.py` | Create/delete SM secret + IRSA role |
| `lifecycle.py` | Suspend / resume / delete |
| `pg_admin.py` | Job in `tenant-<platform>` to `DROP ROLE` / policy |
| `adopt.py` | Mark existing AWS identity as CP-owned |
| `store.py` | File-backed registry (`data/tenants.json`) |
| `infra.py` | Legacy `ensure_infra` (tfvars + tofu apply) |

OpenTofu still supplies: `rds_host`, `migrator_irsa_role_arn`, `oidc_provider_*`, `public_subnet_cidrs`, `alb_logs_bucket`, `platform_tenant_id`, `ingress_mode`.

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
| delete | Drop PG role/policy → helm uninstall → delete ns → delete SM+IRSA → remove registry |

---

## API / CLI

| Method | Path / command | Effect |
|--------|----------------|--------|
| `POST` | `/tenants` | Create → ACTIVE |
| `GET` | `/tenants`, `/tenants/{id}` | List / status |
| `POST` | `/tenants/{id}/suspend` | Suspend |
| `POST` | `/tenants/{id}/resume` | Resume |
| `DELETE` | `/tenants/{id}` | Delete |
| CLI | `cli.py create\|suspend\|resume\|delete\|list\|adopt` | Same |

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

Isolation suite + manual control-plane exercises are recorded in [`VERIFICATION.md`](./VERIFICATION.md).

Acceptance rule: anything the CP provisions must keep [`tests/`](../../tests/) green for the isolation contract (fixtures still use tenants `a` / `b` over `TENANT_BASE_URL`).

---

## What’s left (product, not lab blockers)

- HTTPS (ACM) + domain
- PrivateLink for corporate tenants
- Shrink NAT via interface VPCEs
- Run control plane as an in-cluster service with its own IRSA (today: laptop process + operator AWS creds)
- App-user tokens with `tenant_id` claim (stop trusting only pod env)
