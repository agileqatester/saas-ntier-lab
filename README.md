# ntier-app

AWS n-tier lab: VPC, NAT instance, EKS, RDS, Secrets Manager, Helm. Designed and deployed a cost-optimized, multi-tenant EKS platform featuring path-based ALB routing, granular IRSA least-privilege access, and PostgreSQL Row-Level Security (RLS) to guarantee strict tenant isolation on shared compute.

This repository is a **personal lab**, not a production account. IaC is Terraform/HCL; examples use OpenTofu (`tofu`).

## Architecture

![saas-ntier-lab architecture](architecture.jpg)

**Private workloads by default; restricted public EKS control-plane access for Dev.** EKS nodes and RDS ENIs have **no public IPs** and **no IGW** on their route tables. The only IGW is on the **left edge**, for two Dev exceptions: (1) self-serve customer traffic to the public ALB, (2) NAT egress so nodes can pull images. The **EKS API** is `public+private`: private access is on, and public access is limited to your `/32` (`endpoint_public_access=true`, `api_allowed_cidrs`). That is not a private-only control plane — kube-apiserver is still reachable from the internet for that CIDR. Set `endpoint_public_access=false` for private-only.

**Customer path:** product edge is **HTTPS :443** on the ALB (ACM). Dev is **HTTP :80** locked to your `/32` because there is no domain or certificate yet. ALB→pod is **IP targets** via the **AWS Load Balancer Controller (LBC)**: one shared ALB, Ingress paths `/tenant-<id>` → ClusterIP Service. Helm `PATH_PREFIX` strips the prefix so kube probes and the app still use `/health`. TLS would terminate at the ALB. Do not send customer traffic through NAT.

**LBC (AWS Load Balancer Controller):** a controller that runs **inside the EKS cluster**. It watches Kubernetes **Ingress** objects and creates/updates the AWS **ALB** (listeners, rules, targets). That is how path `/tenant-a` reaches a **ClusterIP** Service without NodePorts. On the architecture diagram, “LBC + ClusterIP Ingress” on the EKS node means the controller pods share that node with tenant workloads (`replicaCount=1` in Dev).

**Why shared Ingress (not NodePort):** NodePort-per-tenant + OpenTofu listener rules do not scale toward ~100 tenants. Default `ingress_mode=alb_controller` installs the LBC on a `t4g.medium` node. Legacy `ingress_mode=nodeport` keeps the old Terraform ALB + NodePort map.

**Shared ALB `group.name` is a trust boundary.** Any Ingress in that group can change the shared load balancer. Tenant namespaces are not allowed to pick a different group or class: a `ValidatingAdmissionPolicy` (Helm chart `platform-guardrails`, installed by the control plane) denies wrong `group.name`, wrong `ingressClassName`, or a path outside `/{namespace}`. The tenant ServiceAccount has a namespaced Role with **no** Ingress verbs — only the control plane Helm release creates tenant Ingress. This is required before calling the shared edge production-safe.

**NAT (Dev egress only):** private nodes → NAT → IGW for image pulls and APIs we did not endpoint yet. Later: interface VPCEs and/or PrivateLink, then NAT can go.

**Operator path (you):** kubectl to the EKS API. **SSM to the EKS worker node** for debug that kubectl cannot do (kubelet, CNI, disk). That is not a bastion and not a path to other subnets. NAT has SSM only so you can repair iptables on the NAT box itself — it is not drawn as an access path.

**Why us-east-1b looks empty:** AWS will not create an ALB (or an RDS subnet group) in one AZ. Compute stays in **1a** (one NAT, one node). **1b** has empty public and private subnets so the ALB can place an ENI in a second AZ, and so RDS can use two private subnets when you set `enable_rds`. Subnets are free; you are not paying for a second node.

Private subnets egress via the NAT instance; S3 uses a **gateway** endpoint (no NAT).

**RDS vs S3/SNS:** RDS is an AWS-managed engine, but the instance still has **ENIs in your private subnets** and a security group (pods reach it on 5432 inside the VPC). S3, SNS, and CloudWatch are regional APIs — they sit outside the VPC. The diagram puts RDS with the other managed icons; the dashed line back into **1a/1b private subnets** is the network attachment. Off by default (`enable_rds`).

**Pooled tenants (same platform):** namespaces on one shared EKS cluster, one shared Postgres — no stack-per-tenant, no database-per-tenant. Isolation is enforced at independent layers — **authorization, network, identity, data, and compute**; see [Pooled tenants](#pooled-tenants). The public ALB is path-based (`/tenant-<id>`) on the default ELB DNS name — no purchased domain. See [docs/saas/TENANT_CONTROL_PLANE.md](docs/saas/TENANT_CONTROL_PLANE.md) and [docs/saas/VERIFICATION.md](docs/saas/VERIFICATION.md).

**Who owns what:**

```text
OpenTofu
 ├── VPC
 ├── EKS
 ├── RDS
 ├── NAT
 ├── LBC infrastructure
 └── platform infrastructure

Tenant Control Plane
 ├── tenant identity
 ├── Secrets Manager
 ├── IRSA
 ├── tenant namespace
 ├── Helm
 ├── lifecycle
 └── reconciliation

Kubernetes
 ├── NetworkPolicy
 ├── ResourceQuota
 ├── RBAC
 └── admission guardrails

PostgreSQL
 └── final data isolation via RLS
```

Keep the VPC. Destroy NAT, EKS, ALB, and RDS after a test. Diagram: [architecture.jpg](architecture.jpg) (GitHub README image). **Authoritative editable source:** [architecture.drawio](architecture.drawio) (regenerate jpg/png/svg from draw.io). There is no Mermaid `architecture.mmd` — older NodePort sketches were removed so the repo cannot drift back to NP 30080/30081.

## What’s next

**Done in this lab** ([VERIFICATION.md](docs/saas/VERIFICATION.md)): pooled multi-tenancy, shared LBC Ingress + `platform-guardrails`, Tenant Control Plane (create / suspend / resume / reconcile / delete), lab `X-Lab-User` authorization, tighter NetPol egress, CP API bind safety (`CP_API_TOKEN`).

Remaining product hardening:

1. **Real authentication** — replace lab `X-Lab-User` with OIDC/OAuth2 (Cognito / IAM Identity Center) and proper app tokens.
2. **HTTPS on the ALB** — ACM on a domain you **own**. A Route 53 private zone does not get a public cert and does not resolve from your laptop.
3. **PrivateLink provider** — enterprise customers attach privately; they never use the IGW.
4. **Shrink NAT** — interface VPC endpoints for ECR/EKS/SSM APIs so private nodes do not need internet egress; then NAT can go.
5. **Control plane as a service** — today it is a laptop Flask/CLI process with operator AWS creds; later in-cluster with its own IRSA + OIDC.

## Layout

```
bootstrap/                 # S3 + DynamoDB + KMS for remote state (~$1/month). Public-repo path.
modules/                   # Reusable modules (VPC, NAT, EKS, RDS, ALB, WAF, …)
env/dev/network/           # Keep: VPC, subnets, IGW, S3 gateway endpoint (Stage 2+)
env/dev/workload/          # Destroy after tests: NAT, EKS, LBC/ALB, optional RDS
control-plane/             # Tenant API + CLI (identity + lifecycle + reconcile)
helm/test-app/             # App chart (ClusterIP + Ingress + lab auth; onboard library)
helm/platform-guardrails/  # ValidatingAdmissionPolicy for shared ALB Ingress group
helm/fluent-bit/           # DaemonSet → CloudWatch Logs (/name_prefix/app), tenant_id in JSON
docs/saas/                 # Control plane design + verification log
tests/                     # Unit + isolation + CP contract (pytest)
```

Do **not** `tofu apply` from the repo root. The root `main.tf` is the previous monolith and is not the Dev path anymore.

Dev uses **SSM Session Manager on the EKS node** for host debug, not a public SSH bastion. NAT is egress only.

## Prerequisites

- OpenTofu >= 1.6 (`tofu version`). HashiCorp Terraform is not required.
- AWS CLI v2, credentials configured (`aws sts get-caller-identity`)
- kubectl (when you reach EKS)
- Helm 3+ (when you deploy the test app)
- Session Manager plugin (`brew install --cask session-manager-plugin`) for SSM

## Dev cost habit

| Keep overnight | Destroy after a basic test |
|----------------|----------------------------|
| VPC, subnets, route tables, IGW, S3 **gateway** endpoint | NAT instance, public IPv4, EKS, RDS, ALB |
| Bootstrap state bucket / lock table / KMS (~$1/month) | Interface VPC endpoints (not used in Dev) |

EKS has **no create fee**. The control plane is **$0.10/hour** (~$73/month) the whole time the cluster exists, including the ~15 minutes AWS spends creating it. Kubernetes versions in **extended** support are **$0.60/hour** — Dev pins a **standard-support** version (1.35). Destroy `env/dev/workload` when you stop; do not leave EKS overnight.

App logs in CloudWatch are **cents** on this lab (ingest **$0.50/GB**, storage **$0.03/GB-month**, 7-day retention). Fluent Bit is a DaemonSet on the existing node — no extra EC2. Do **not** turn on Container Insights.

Public subnets + IGW are required for the NAT instance (private outbound: image pulls, AWS APIs) and later for an internet-facing ALB. NAT is not required for ALB inbound.

## State (S3 for the public repo)

This laptop can keep using **local** state until you publish. The public GitHub copy should use the **S3 backend**: apply `bootstrap/` once, then uncomment `backend.tf` in each stack (different `key`s), then `tofu init -migrate-state`.

Do **not** commit `.tfstate`, real bucket names, or `terraform.tfvars`. The bucket stays private; state can contain resource IDs and the EKS API CIDR. Encryption and DynamoDB locking are created by bootstrap.

```bash
# 1) Remote state (once per account). Public-repo default.
cd bootstrap
cp terraform.tfvars.example terraform.tfvars
# set a globally unique state_bucket_name (yours, not committed)
tofu init && tofu apply
# then uncomment backend.tf in env/dev/network and env/dev/workload
# tofu init -migrate-state in each stack

# 2) Network (Stage 2 — VPC). Leave applied.
cd env/dev/network
cp terraform.tfvars.example terraform.tfvars
tofu init
tofu plan  -var-file=terraform.tfvars
tofu apply -var-file=terraform.tfvars

# 3) Workload (NAT + EKS + ALB). Pass my_ip on the CLI — do not write it to tfvars.
cd env/dev/workload
cp terraform.tfvars.example terraform.tfvars
tofu init
tofu apply -var-file=terraform.tfvars \
  -var="my_ip=$(curl -s https://checkip.amazonaws.com)/32"
# ~15 min, then (helm_install refreshes kubeconfig — recreate invalidates the old API DNS):
eval "$(tofu output -raw helm_install)"
curl -s "$(tofu output -raw alb_url)/tenant-a/health"
tofu destroy -var-file=terraform.tfvars \
  -var="my_ip=$(curl -s https://checkip.amazonaws.com)/32"
```

If you omit `-var`, OpenTofu prompts for `my_ip`. Use `x.x.x.x/32`. Keep `env/dev/network` applied.

Default workload: NAT instance, EKS (one On-Demand `t4g.medium`), AWS Load Balancer Controller + shared HTTP ALB (open to your `/32` only; Ingress paths `/tenant-<id>`), S3 access logs, SNS 5xx alarm. **RDS is off.** No port-forward — `curl http://<alb_dns>/tenant-a/health`.

To add Postgres, set `enable_rds = true` in `terraform.tfvars`, apply again (same `my_ip` `-var`), then `eval "$(tofu output -raw helm_install)"`. That flag creates RDS, the migrator IRSA role, and the **vpc-cni** addon (`enableNetworkPolicy`). With `manage_tenant_identity=false`, per-tenant secrets/IRSA are created by the control plane (not OpenTofu `tenant_ids`).

With RDS on, `helm_install` refreshes kubeconfig and can bootstrap platform tenants when identity is still tofu-managed. Prefer `control-plane/cli.py` for day-2 tenants. Destroy/recreate of the cluster gets a **new** API hostname; an old `~/.kube/config` will fail with `no such host`.

## Pooled tenants

Same EKS cluster, same RDS instance — the SaaS pattern this lab is built to prove out. Isolation isn't a single control; it's layered so no one bug removes it:

Authentication is intentionally out of scope for this lab. Tenant authorization is simulated to demonstrate the authorization boundary; production deployments should integrate an external OIDC/OAuth2 identity provider.

```text
              LAB USER (X-Lab-User)
                     │
                     ▼
           Tenant authorization
           (static map in the app)
                     │
                     ▼
           ┌──────────────────┐
           │ Tenant namespace │
           └────────┬─────────┘
                    │
              IRSA isolation
                    │
                    ▼
                 RDS/RLS
```

- **Authorization:** product routes require `X-Lab-User` (`alice` → tenant `a`, `bob` → `b`, `admin` → both; tests also use `user-a` / `user-b`). Wrong tenant is **403**; missing/unknown user is **401**. `/health` stays open for probes. The header is **not** trusted by PostgreSQL — the pod still sets `SET LOCAL app.tenant_id` from Helm `tenant.id`, then RLS.
- **Network:** each tenant sits in its own namespace. **Ingress** NetworkPolicy is default-deny between tenants (ALB public-subnet CIDRs + same-namespace only — not the VPC CIDR). **Egress** is also default-deny, then explicitly allows DNS (CoreDNS), Postgres (private subnet CIDRs :5432), same-namespace :8080, and HTTPS :443 for this lab’s pip + AWS APIs via NAT. Production should drop `0.0.0.0/0:443` and allow only interface VPC endpoints. Enforced by the VPC CNI network policy engine (not just Kubernetes-native, which some CNIs ignore).
- **Identity:** each tenant pod assumes its **own** IRSA role, trusted only by its own service account (`system:serviceaccount:tenant-a:test-app`), scoped only to read its own Secrets Manager secret. Tenant B's pods have no IAM path to tenant A's credentials, and vice versa.
- **Data:** each tenant has its own Postgres login, and the table has `FORCE ROW LEVEL SECURITY` with a policy bound to that specific role. App code sets `SET LOCAL app.tenant_id` on every connection checkout as a second check, but the role-bound policy is the one that actually matters — `/db/records` has **no** `WHERE tenant_id` in the query at all. Postgres does the filtering, not application code, which means a missing `WHERE` clause in a future endpoint can't leak cross-tenant data.
- **Deletion order:** teardown is deliberate — disable application access → revoke Postgres role (`NOLOGIN` / password rotate / `DROP ROLE`) → delete Kubernetes → IRSA → secret. A failed DB revoke becomes `DELETE_FAILED` and **stops** before k8s/IAM/secret cleanup, so delete does not leave orphaned database access. Retry is safe; steps are idempotent.
- **Compute:** each namespace gets a `ResourceQuota` capping aggregate CPU/memory (`requests.cpu: 100m`, `limits.cpu: 500m`, `limits.memory: 512Mi`) and pod count (2), plus a `LimitRange` setting default requests/limits for any container that doesn't declare its own. On a single shared node, this is what stops one tenant's traffic spike or misconfigured pod from starving the other tenant's compute — the same fairness goal as the other three layers, just applied to CPU and memory instead of packets, credentials, or rows.

The bootstrap migration Job (IRSA `tenant-a:test-app-migrate`, `platform_tenant_id=a`) creates the table, enables `FORCE ROW LEVEL SECURITY`, and provisions each tenant's role + policy when secrets are present.

### Add a tenant (Tenant Control Plane)

Day-2 tenants are **not** OpenTofu `tenant_ids` + curl. The **Tenant Control Plane** owns Secrets Manager + IRSA + Helm/Ingress lifecycle. OpenTofu keeps the shared platform (VPC, EKS, RDS, LBC, migrator).

```text
CREATE ──► PROVISIONING ──► ACTIVE
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
            SUSPENDED                   DELETING
                 │                         │
                 ▼                    ┌────┴────┐
              ACTIVE                  ▼         ▼
                                    GONE   DELETE_FAILED
                                               │
                                               └── retry DELETE
```

| Step | What runs |
|------|-----------|
| Create | SM secret + IRSA → refresh migrate Job → namespace / NetPol / quota / Helm ClusterIP + Ingress |
| Suspend | replicas=0, drop Ingress (data + secret kept) |
| Resume | bring workload + Ingress back → ACTIVE |
| Delete | Disable access → `NOLOGIN`/rotate/`DROP ROLE` (retry) → k8s → IRSA → secret. Failure after DB revoke is skipped; failure **during** DB revoke → `DELETE_FAILED` (retry). Lab secret delete is force-delete (`CP_SECRET_RECOVERY_DAYS` for a window). |

```bash
export TOFU_DIR=$PWD/env/dev/workload
export MY_IP="$(curl -s https://checkip.amazonaws.com)/32"
# first time: python3 -m venv control-plane/.venv && control-plane/.venv/bin/pip install -r control-plane/requirements.txt

control-plane/.venv/bin/python control-plane/cli.py create d
control-plane/.venv/bin/python control-plane/cli.py list
control-plane/.venv/bin/python control-plane/cli.py suspend d
control-plane/.venv/bin/python control-plane/cli.py resume d
control-plane/.venv/bin/python control-plane/cli.py reconcile d
control-plane/.venv/bin/python control-plane/cli.py delete d
```

Same operations via local API (`control-plane/.venv/bin/python control-plane/app.py` on `127.0.0.1:8088`). Non-loopback bind requires `CP_API_TOKEN`. Details: [control-plane/README.md](control-plane/README.md), [docs/saas/TENANT_CONTROL_PLANE.md](docs/saas/TENANT_CONTROL_PLANE.md).

**First-time platform:** apply workload with `enable_rds=true`, `ingress_mode=alb_controller`, `manage_tenant_identity=false`, then `cli.py create` for `a` / `b` (isolation fixtures) or `cli.py adopt` after a one-time bootstrap. Legacy: `manage_tenant_identity=true` + deprecated `onboard_tenant.py` — prefer the CLI.

### Validation & testing

Three layers: **(1)** unit tests (no cluster), **(2)** isolation + smoke + authz against permanent tenants `a`/`b` on the live stack, **(3)** control-plane lifecycle / contract tests (and manual CLI checks on a throwaway tenant). Full log: [docs/saas/VERIFICATION.md](docs/saas/VERIFICATION.md).

#### Tenant Isolation matrix (ACTIVE `a` / `b`)

Positive = tenant reaches **own** boundary. Negative = cross-tenant attempt is **blocked**.

```text
                    Tenant Isolation Tests

             ┌─────────┬─────────┬─────────┬─────────┬─────────┐
             │ Authz   │ Network │ IAM     │ Data    │ Compute │
─────────────┼─────────┼─────────┼─────────┼─────────┼─────────┤
user-a → A   │ PASS    │ PASS    │ PASS    │ PASS    │ PASS    │
user-a → B   │ 403     │ BLOCK   │ BLOCK   │ BLOCK   │ N/A     │
user-b → A   │ 403     │ BLOCK   │ BLOCK   │ BLOCK   │ N/A     │
user-b → B   │ PASS    │ PASS    │ PASS    │ PASS    │ PASS    │
```

Authz is the lab `X-Lab-User` map (no Cognito/OIDC). Network/IAM/Data still apply after a user is allowed in. Compute is per-namespace quota (noisy-neighbor), not A→B API calls — hence N/A on the cross rows.

#### Control-plane lifecycle checks (manual / CLI)

Exercised while building the CP (tenants `f` / `g`); re-run after CP changes:

```text
✓ tenant can be created
✓ tenant eventually becomes ACTIVE
✓ ACTIVE tenant can access own data
✓ SUSPENDED tenant cannot access API (ALB 503)
✓ SUSPENDED tenant data remains
✓ tenant can resume → ACTIVE
✓ DELETED tenant cannot access API
✓ DELETED tenant resources removed (ns / Ingress)
✓ DELETED tenant credentials revoked (DB role first, then IRSA, then secret)
✓ if DROP ROLE fails → DELETE_FAILED; k8s/IAM/secret still present; retry delete
```

#### Automated suite (`pytest`)

```bash
python3 -m venv .venv-tests && .venv-tests/bin/pip install -r tests/requirements.txt
export TENANT_BASE_URL="$(cat env/dev/workload/.alb_url)"   # live stack only
# kubectl already pointed at the cluster for isolation/smoke
.venv-tests/bin/pytest tests/ -v
# or split:
.venv-tests/bin/pytest tests/unit tests/control_plane -v   # no cluster required
.venv-tests/bin/pytest tests/smoke tests/isolation -v      # needs live stack + X-Lab-User map
```

**Collected suite size:** **108** tests (`pytest --collect-only`): **63** unit + **9** control-plane contract + **8** smoke + **28** isolation (includes authz, NetPol egress, Ingress guardrails). Parametrized cases are counted separately, so this is higher than the number of `def test_*` functions.

```text
SaaS Tenant Isolation Tests
============================

SMOKE
✓ test_tenant_a_namespace_exists / test_tenant_b_namespace_exists
✓ test_tenant_a_workload_ready / test_tenant_b_workload_ready
✓ test_tenant_a_is_healthy / test_tenant_b_is_healthy
✓ test_tenant_a_db_reachable / test_tenant_b_db_reachable

DATABASE ISOLATION
✓ test_tenant_a_can_read_own_records
✓ test_tenant_b_can_read_own_records
✓ test_tenant_a_cannot_read_tenant_b_records_via_query
✓ test_tenant_a_cannot_create_tenant_b_record
✓ test_missing_tenant_context_returns_no_data

AUTHORIZATION (lab user)
✓ user-a → tenant-a OK; user-a → tenant-b 403
✓ user-b → tenant-b OK; user-b → tenant-a 403
✓ admin → both tenants OK
✓ missing / unknown X-Lab-User → 401
✓ header does not change Postgres tenant_id (RLS still pod-bound)
✓ /health remains unauthenticated

NETWORK ISOLATION
✓ test_tenant_a_can_reach_own_service
✓ test_tenant_b_can_reach_own_service
✓ test_tenant_a_cannot_reach_tenant_b
✓ test_tenant_b_cannot_reach_tenant_a
✓ egress to internet :80 denied (DNS / Postgres / lab HTTPS still allowed)

SHARED ALB GUARDRAILS
✓ tenant SA cannot create Ingress
✓ foreign group.name denied
✓ path /tenant-b from namespace tenant-a denied

IAM ISOLATION
✓ test_tenant_a_can_read_own_secret
✓ test_tenant_b_can_read_own_secret
✓ test_tenant_a_cannot_read_tenant_b_secret
✓ test_tenant_b_cannot_read_tenant_a_secret

COMPUTE ISOLATION
✓ test_tenant_a_quota_blocks_extra_pod
✓ test_tenant_b_remains_healthy_when_tenant_a_hits_quota
```

#### Spot checks (curl / kubectl)

Quick manual positives/negatives (same contract as pytest; optional once the suite is green):

```bash
ALB="$(cat env/dev/workload/.alb_url)"

# positive — own tenant (simulated user)
curl -sS "$ALB/tenant-a/health"    # unauthenticated on purpose (probes)
curl -sS -H 'X-Lab-User: alice' "$ALB/tenant-a/"
curl -sS -H 'X-Lab-User: bob' "$ALB/tenant-b/"
curl -sS -H 'X-Lab-User: alice' -X POST "$ALB/tenant-a/db/items" \
  -H 'Content-Type: application/json' -d '{"message":"from-a"}'
curl -sS -H 'X-Lab-User: alice' "$ALB/tenant-a/db/records?limit=5"   # only a

# negative — authorization
curl -sS -H 'X-Lab-User: alice' "$ALB/tenant-b/"   # 403
curl -sS "$ALB/tenant-a/"                         # 401 missing user

# negative — spoof / missing path
curl -sS "$ALB/health"                                    # 404 (no tenant prefix)
curl -sS -H 'X-Lab-User: alice' "$ALB/tenant-a/db/records?tenant_id=b&limit=5"  # still a (RLS)

# negative — east-west
kubectl run netcheck -n tenant-b --rm -it --image=busybox --restart=Never -- \
  wget -qO- --timeout=3 http://test-app.tenant-a.svc.cluster.local:8080/health
# pass: timeout / fail

# negative — quota
kubectl -n tenant-a scale deploy/test-app --replicas=3
kubectl -n tenant-a get deploy test-app   # 2/3; extra pod never created
kubectl -n tenant-a scale deploy/test-app --replicas=1
```

### Logs

Tenant identity is in the log pipeline, not only in Postgres. Each request JSON line on stdout includes `tenant_id` from the Helm value (same source as RLS — not a client header). Fluent Bit runs as a DaemonSet with IRSA (`amazon-cloudwatch:fluent-bit`) and can `PutLogEvents` only to `/${name_prefix}/app` (Dev: `/ntier-dev/app`, 7-day retention). It tails tenant container logs, merges the JSON so `tenant_id` is a first-class field, and does not ship `/health` probes. Cost on this lab is **cents** (ingest $0.50/GB). Do **not** enable Container Insights.

That is the observability half of pooled tenancy: Insights can `stats count(*) by tenant_id` the same way RLS filters rows.

### Validation (logs)

Do **not** use the log group **Log streams** tab or Live Tail for this proof. Those screens show raw lines (and used to fill with Werkzeug `GET /health`). Insights is **CloudWatch → Logs → Log Analytics** (AWS renamed Logs Insights). Select log group `/ntier-dev/app`, last 1 hour.

Generate traffic that is not `/health`, wait ~30s:

```bash
ALB="$(cat env/dev/workload/.alb_url)"
curl -sS -H 'X-Lab-User: alice' "$ALB/tenant-a/"
curl -sS -H 'X-Lab-User: bob' "$ALB/tenant-b/"
curl -sS -H 'X-Lab-User: alice' "$ALB/tenant-a/db/records?limit=1"
```

```
fields @timestamp, tenant_id, path, status
| filter ispresent(tenant_id)
| sort @timestamp desc
| limit 20
```

Pass: events with `"tenant_id":"a"` (and b) and paths like `/` or `/db/records`. Then:

```
fields tenant_id
| filter ispresent(tenant_id)
| stats count(*) by tenant_id
```

Pass: one row per tenant that you hit. Direct link: CloudWatch Logs Insights in `us-east-1` on `/ntier-dev/app`.

## License

Apache 2.0. See [LICENSE](LICENSE).
