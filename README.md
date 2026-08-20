# ntier-app

AWS n-tier lab: VPC, NAT instance, EKS, RDS, Secrets Manager, Helm. Designed and deployed a cost-optimized, multi-tenant EKS platform featuring path-based ALB routing, granular IRSA least-privilege access, and PostgreSQL Row-Level Security (RLS) to guarantee strict tenant isolation on shared compute.

This repository is a **personal lab**, not a production account. IaC is Terraform/HCL; examples use OpenTofu (`tofu`).

## Architecture

![saas-ntier-lab architecture](architecture.jpg)

**Private by default:** EKS nodes and RDS ENIs have **no public IPs** and **no IGW** on their route tables. The only IGW is on the **left edge**, for two Dev exceptions: (1) self-serve customer traffic to the public ALB, (2) NAT egress so nodes can pull images.

**Customer path:** product edge is **HTTPS :443** on the ALB (ACM). Dev is **HTTP :80** locked to your `/32` because there is no domain or certificate yet. ALB→node is still VPC HTTP to NodePort **30080 + index** in `var.tenant_ids` (`a` → 30080, `b` → 30081, `c` → 30082). TLS would terminate at the ALB. Do not send customer traffic through NAT.

**Why NodePort:** the ALB is Terraform-managed with **instance targets** (the EKS node’s private IP). There is no AWS Load Balancer Controller (it would not fit on a single `t4g.small`). Each tenant Service owns one NodePort; listener rules split `/tenant-<id>*`. Health checks hit `/health` on the NodePort (they do not use the listener path). Helm `PATH_PREFIX` strips the prefix so kube probes and the app still use `/health`. Inside the cluster this is still a normal Service → pod; NodePort is only the ALB’s hook onto the node.

**NAT (Dev egress only):** private nodes → NAT → IGW for image pulls and APIs we did not endpoint yet. Later: interface VPCEs and/or PrivateLink, then NAT can go.

**Operator path (you):** kubectl to the EKS API. **SSM to the EKS worker node** for debug that kubectl cannot do (kubelet, CNI, disk). That is not a bastion and not a path to other subnets. NAT has SSM only so you can repair iptables on the NAT box itself — it is not drawn as an access path.

**Why us-east-1b looks empty:** AWS will not create an ALB (or an RDS subnet group) in one AZ. Compute stays in **1a** (one NAT, one node). **1b** has empty public and private subnets so the ALB can place an ENI in a second AZ, and so RDS can use two private subnets when you set `enable_rds`. Subnets are free; you are not paying for a second node.

Private subnets egress via the NAT instance; S3 uses a **gateway** endpoint (no NAT).

**RDS vs S3/SNS:** RDS is an AWS-managed engine, but the instance still has **ENIs in your private subnets** and a security group (pods reach it on 5432 inside the VPC). S3, SNS, and CloudWatch are regional APIs — they sit outside the VPC. The diagram puts RDS with the other managed icons; the dashed line back into **1a/1b private subnets** is the network attachment. Off by default (`enable_rds`).

**Pooled tenants (same platform):** namespaces from `var.tenant_ids` (default `a` / `b` / `c`) on one shared EKS cluster, one shared Postgres — no stack-per-tenant, no database-per-tenant. Isolation is enforced at four independent layers — network, identity, data, and compute — so a gap in one doesn't collapse the whole boundary; see [Pooled tenants](#pooled-tenants) below for the full breakdown. The public ALB is path-based on the default ELB DNS name — `/tenant-<id>*` → NodePort **30080 + index** — so no purchased domain is required. `helm/test-app/onboard_tenant.py` handles the k8s half of onboarding (reads `tofu output -json`); IAM/secrets stay in OpenTofu `for_each` so a new tenant is one list entry plus one script invocation, not a hand-wired stack.

Keep the VPC. Destroy NAT, EKS, ALB, and RDS after a test. Diagram: [architecture.jpg](architecture.jpg) (GitHub README image). Draw.io source: [architecture.mmd](architecture.mmd).

## What’s next

Same shared platform. No rewrite. Pooled multi-tenancy — routing, network isolation, IAM scoping, and row-level data isolation — is done and tested (see Validation below). What's left is edge/network hardening:

1. **HTTPS on the ALB** — ACM on a domain you **own**. A Route 53 private zone does not get a public cert and does not resolve from your laptop.
2. **PrivateLink provider** — enterprise customers attach privately; they never use the IGW.
3. **Shrink NAT** — interface VPC endpoints for ECR/EKS/SSM APIs so private nodes do not need internet egress; then NAT can go.

## Layout

```
bootstrap/          # S3 + DynamoDB + KMS for remote state (~$1/month). Public-repo path.
modules/            # Reusable modules (VPC, NAT, EKS, RDS, ALB, WAF, …)
env/dev/network/    # Keep: VPC, subnets, IGW, S3 gateway endpoint (Stage 2+)
env/dev/workload/   # Destroy after tests: NAT, EKS, ALB, optional RDS
helm/test-app/      # App chart (NodePort 30080+index via tofu; onboard_tenant.py)
helm/fluent-bit/    # DaemonSet → CloudWatch Logs (/name_prefix/app), tenant_id in JSON
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

Default workload: NAT instance, EKS (one On-Demand `t4g.small`), HTTP ALB (open to your `/32` only; paths `/tenant-<id>*` from `var.tenant_ids`, default 404), S3 access logs, SNS 5xx alarm. **RDS is off.** No port-forward — `curl http://<alb_dns>/tenant-a/health`.

To add Postgres, set `enable_rds = true` in `terraform.tfvars`, apply again (same `my_ip` `-var`), then `eval "$(tofu output -raw helm_install)"`. That flag creates RDS, per-tenant secrets/IRSA, the migrator role, and the **vpc-cni** addon (`enableNetworkPolicy`). `list-addons` is empty until that addon resource exists — do not `tofu import` it.

With RDS on, `helm_install` refreshes kubeconfig, waits for a Ready node, and runs `onboard_tenant.py --all` (every `var.tenant_ids` entry). Destroy/recreate of the cluster gets a **new** API hostname; an old `~/.kube/config` will fail with `no such host`.

## Pooled tenants

Same EKS cluster, same RDS instance, tenants from `var.tenant_ids` (default `a`, `b`, `c`) — the SaaS pattern this lab is built to prove out. Isolation isn't a single control; it's layered so no one bug removes it:

- **Network:** each tenant sits in its own namespace with a default-deny `NetworkPolicy` between them, enforced by the VPC CNI's network policy support (not just Kubernetes-native, which some CNIs ignore).
- **Identity:** each tenant pod assumes its **own** IRSA role, trusted only by its own service account (`system:serviceaccount:tenant-a:test-app`), scoped only to read its own Secrets Manager secret. Tenant B's pods have no IAM path to tenant A's credentials, and vice versa.
- **Data:** each tenant has its own Postgres login, and the table has `FORCE ROW LEVEL SECURITY` with a policy bound to that specific role. App code sets `SET LOCAL app.tenant_id` on every connection checkout as a second check, but the role-bound policy is the one that actually matters — `/db/records` has **no** `WHERE tenant_id` in the query at all. Postgres does the filtering, not application code, which means a missing `WHERE` clause in a future endpoint can't leak cross-tenant data.
- **Compute:** each namespace gets a `ResourceQuota` capping aggregate CPU/memory (`requests.cpu: 100m`, `limits.cpu: 500m`, `limits.memory: 512Mi`) and pod count (2), plus a `LimitRange` setting default requests/limits for any container that doesn't declare its own. On a single shared node, this is what stops one tenant's traffic spike or misconfigured pod from starving the other tenant's compute — the same fairness goal as the other three layers, just applied to CPU and memory instead of packets, credentials, or rows.

The bootstrap migration Job (running as its own IRSA-scoped service account on the **first** `tenant_ids` entry, `tenant-a:test-app-migrate`) creates the table, enables `FORCE ROW LEVEL SECURITY`, and provisions each tenant's role + policy on first run.

### Add a tenant

Two halves. OpenTofu owns IAM, Secrets Manager, ALB path, and NodePort (`30080 + index` in `tenant_ids`). `helm/test-app/onboard_tenant.py` owns the namespace, Helm release, and NetworkPolicy. The script does **not** take `IRSA_*` env vars; it reads `tofu output -json` (`tenant_irsa_role_arns`, `tenant_secret_names`, `tenant_node_ports`, `rds_host`, migrator role).

**First time** (empty cluster, RDS already on): apply, then onboard every id:

```bash
cd env/dev/workload
tofu apply -var-file=terraform.tfvars \
  -var="my_ip=$(curl -s https://checkip.amazonaws.com)/32"
eval "$(tofu output -raw helm_install)"
# helm_install already runs: python3 .../onboard_tenant.py --all
```

**Add one more** (example: `d` while `a`/`b`/`c` are live):

1. Edit `env/dev/workload/terraform.tfvars` (do not commit it):

   ```hcl
   enable_rds  = true
   tenant_ids  = ["a", "b", "c", "d"]
   ```

   Keep the existing keys in the same order. NodePort for `d` is **30083**. The first id still runs migrate.

2. Apply so OpenTofu creates the IRSA role, secret, ALB rule `/tenant-d*`, and SG/NodePort:

   ```bash
   cd env/dev/workload
   tofu apply -var-file=terraform.tfvars \
     -var="my_ip=$(curl -s https://checkip.amazonaws.com)/32"
   ```

3. Kubernetes onboard (refreshes tenant `a` so migrate sees `d`'s secret, then installs `tenant-d`):

   ```bash
   python3 ../../../helm/test-app/onboard_tenant.py d
   curl -sS "$(tofu output -raw alb_url)/tenant-d/health"
   ```

   Expect `tenant_id":"d"` and `database":"connected"`.

`--all` re-onboards every id in the current output. Use it after a cluster recreate. Use a single id (`d`) when the others are already running. A fourth app pod still fits a `t4g.small` (max 11 pods); do not keep growing this node as if it were production.

### Validation

```bash
ALB="$(tofu output -raw alb_url)"

curl -sS "$ALB/tenant-a/health"    # tenant_id a, database connected
curl -sS "$ALB/tenant-b/health"    # tenant_id b
curl -sS "$ALB/tenant-c/health"    # tenant_id c
curl -sS "$ALB/health"             # 404

curl -sS "$ALB/tenant-a/db/init"   # rls true, force_rls true

curl -sS -X POST "$ALB/tenant-a/db/items" -H 'Content-Type: application/json' -d '{"message":"from-a"}'
curl -sS -X POST "$ALB/tenant-b/db/items" -H 'Content-Type: application/json' -d '{"message":"from-b"}'
curl -sS -X POST "$ALB/tenant-c/db/items" -H 'Content-Type: application/json' -d '{"message":"from-c"}'
curl -sS "$ALB/tenant-a/db/records?limit=5"              # only a
curl -sS "$ALB/tenant-b/db/records?limit=5"              # only b
curl -sS "$ALB/tenant-c/db/records?limit=5"              # only c
curl -sS "$ALB/tenant-a/db/records?tenant_id=b&limit=5"  # still a

aws eks describe-addon --cluster-name ntier-dev-eks-cluster --addon-name vpc-cni --region us-east-1 \
  --query 'addon.{status:status,config:configurationValues}' --output json
# status ACTIVE, config includes enableNetworkPolicy. Query addon.status — a top-level status is always null.
# aws-node should be 2/2 (policy sidecar).

kubectl run netcheck -n tenant-b --rm -it --image=busybox --restart=Never -- \
  wget -qO- --timeout=3 http://test-app.tenant-a.svc.cluster.local:8080/health
# pass: download timed out — proves NetworkPolicy blocks tenant-b from reaching tenant-a even inside the cluster

kubectl -n tenant-a scale deploy/test-app --replicas=3
kubectl -n tenant-a get deploy test-app   # 2/3; extra pod never created (quota admission)
kubectl -n tenant-a scale deploy/test-app --replicas=1

kubectl describe resourcequota -n tenant-a   # shows requests.cpu/memory and limits.cpu/memory used vs hard cap
kubectl describe limitrange -n tenant-a      # shows the default request/limit applied to containers that don't set their own
```

### Logs

Tenant identity is in the log pipeline, not only in Postgres. Each request JSON line on stdout includes `tenant_id` from the Helm value (same source as RLS — not a client header). Fluent Bit runs as a DaemonSet with IRSA (`amazon-cloudwatch:fluent-bit`) and can `PutLogEvents` only to `/${name_prefix}/app` (Dev: `/ntier-dev/app`, 7-day retention). It tails tenant container logs, merges the JSON so `tenant_id` is a first-class field, and does not ship `/health` probes. Cost on this lab is **cents** (ingest $0.50/GB). Do **not** enable Container Insights.

That is the observability half of pooled tenancy: Insights can `stats count(*) by tenant_id` the same way RLS filters rows.

### Validation (logs)

Do **not** use the log group **Log streams** tab or Live Tail for this proof. Those screens show raw lines (and used to fill with Werkzeug `GET /health`). Insights is **CloudWatch → Logs → Log Analytics** (AWS renamed Logs Insights). Select log group `/ntier-dev/app`, last 1 hour.

Generate traffic that is not `/health`, wait ~30s:

```bash
ALB="$(tofu output -raw alb_url)"
curl -sS "$ALB/tenant-a/"
curl -sS "$ALB/tenant-b/"
curl -sS "$ALB/tenant-c/"
curl -sS "$ALB/tenant-a/db/records?limit=1"
```

```
fields @timestamp, tenant_id, path, status
| filter ispresent(tenant_id)
| sort @timestamp desc
| limit 20
```

Pass: events with `"tenant_id":"a"` (and b, c) and paths like `/` or `/db/records`. Then:

```
fields tenant_id
| filter ispresent(tenant_id)
| stats count(*) by tenant_id
```

Pass: one row per tenant that you hit. Direct link: CloudWatch Logs Insights in `us-east-1` on `/ntier-dev/app`.

## License

## License

Apache 2.0. See [LICENSE](LICENSE).
