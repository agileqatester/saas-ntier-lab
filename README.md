# ntier-app

AWS n-tier lab: VPC, NAT instance, EKS, RDS, Secrets Manager, Helm. Written in **OpenTofu** (Terraform-compatible HCL). Dev is shaped to stay cheap: keep the free network, destroy paid compute after a test.

This repository is a **personal lab / resume reference**, not a production account.

## Architecture

![saas-ntier-lab architecture](architecture.jpg)

**Private by default:** EKS nodes and RDS ENIs have **no public IPs** and **no IGW** on their route tables. The only IGW is on the **left edge**, for two Dev exceptions: (1) self-serve customer traffic to the public ALB, (2) NAT egress so nodes can pull images.

**Customer path:** product edge is **HTTPS :443** on the ALB (ACM). Dev is **HTTP :80** locked to your `/32` because there is no domain or certificate yet. ALB→node is still VPC HTTP to NodePort **30080** (`/tenant-a*`) and **30081** (`/tenant-b*`). TLS would terminate at the ALB. Do not send customer traffic through NAT.

**Why NodePort 30080/30081:** the ALB is Terraform-managed with **instance targets** (the EKS node’s private IP). There is no AWS Load Balancer Controller (it would not fit on a single `t4g.small`). Each tenant Service owns one NodePort; listener rules split `/tenant-a*` and `/tenant-b*`. Health checks hit `/health` on the NodePort (they do not use the listener path). Helm `PATH_PREFIX` strips the prefix so kube probes and the app still use `/health`. Inside the cluster this is still a normal Service → pod; NodePort is only the ALB’s hook onto the node.

**NAT (Dev egress only):** private nodes → NAT → IGW for image pulls and APIs we did not endpoint yet. Later: interface VPCEs and/or PrivateLink, then NAT can go.

**Operator path (you):** kubectl to the EKS API. **SSM to the EKS worker node** for debug that kubectl cannot do (kubelet, CNI, disk). That is not a bastion and not a path to other subnets. NAT has SSM only so you can repair iptables on the NAT box itself — it is not drawn as an access path.

**Why us-east-1b looks empty:** AWS will not create an ALB (or an RDS subnet group) in one AZ. Compute stays in **1a** (one NAT, one node). **1b** has empty public and private subnets so the ALB can place an ENI in a second AZ, and so RDS can use two private subnets when you set `enable_rds`. Subnets are free; you are not paying for a second node.

Private subnets egress via the NAT instance; S3 uses a **gateway** endpoint (no NAT).

**RDS vs S3/SNS:** RDS is an AWS-managed engine, but the instance still has **ENIs in your private subnets** and a security group (pods reach it on 5432 inside the VPC). S3, SNS, and CloudWatch are regional APIs — they sit outside the VPC. The diagram puts RDS with the other managed icons; the dashed line back into **1a/1b private subnets** is the network attachment. Off by default (`enable_rds`).

**Pooled tenants (same platform):** namespaces `tenant-a` / `tenant-b`, one Postgres, **RLS** (`FORCE ROW LEVEL SECURITY` plus per-role policies and `SET LOCAL app.tenant_id` on checkout). Each tenant has its own DB login, Secrets Manager secret, and IRSA role. The public ALB is path-based on the default ELB DNS name: `/tenant-a*` → NodePort **30080**, `/tenant-b*` → **30081** (no purchased domain). Helm `PATH_PREFIX` strips the path so the app still serves `/health`. ResourceQuota caps each namespace at two pods (scale to 3 → deploy **2/3**; the extra pod is never created). `helm/test-app/onboard-tenant.sh` is the k8s half; IAM stays in OpenTofu `for_each`.

Keep the VPC. Destroy NAT, EKS, ALB, and RDS after a test. Diagram: [architecture.jpg](architecture.jpg) (GitHub README image). Draw.io source: [architecture.mmd](architecture.mmd).

## What’s next

Same shared platform. No rewrite.

1. **HTTPS on the ALB** — ACM on a domain you **own**. A Route 53 private zone does not get a public cert and does not resolve from your laptop.
2. **PrivateLink provider** — enterprise customers attach privately; they never use the IGW.
3. **Shrink NAT** — interface VPC endpoints for ECR/EKS/SSM APIs so private nodes do not need internet egress; then NAT can go.

## Layout

```
bootstrap/          # S3 + DynamoDB + KMS for remote state (~$1/month). Public-repo path.
modules/            # Reusable modules (VPC, NAT, EKS, RDS, ALB, WAF, …)
env/dev/network/    # Keep: VPC, subnets, IGW, S3 gateway endpoint (Stage 2+)
env/dev/workload/   # Destroy after tests: NAT, EKS, ALB, optional RDS
helm/test-app/      # App chart (NodePort 30080/30081; values-tenant-a / values-tenant-b)
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

Default workload: NAT instance, EKS (one On-Demand `t4g.small`), HTTP ALB (open to your `/32` only; paths `/tenant-a*` and `/tenant-b*`, default 404), S3 access logs, SNS 5xx alarm. **RDS is off.** No port-forward — `curl http://<alb_dns>/tenant-a/health`.

To add Postgres, set `enable_rds = true` in `terraform.tfvars`, apply again (same `my_ip` `-var`), then `eval "$(tofu output -raw helm_install)"`. That flag creates RDS, per-tenant secrets/IRSA, the migrator role, and the **vpc-cni** addon (`enableNetworkPolicy`). `list-addons` is empty until that addon resource exists — do not `tofu import` it.

With RDS on, `helm_install` refreshes kubeconfig, waits for a Ready node, and runs `onboard-tenant.sh a` then `b`. Destroy/recreate of the cluster gets a **new** API hostname; an old `~/.kube/config` will fail with `no such host`.

## Pooled tenants

Same EKS and RDS. Each tenant pod uses **its own** Postgres role and secret. A Job in `tenant-a` (master secret) creates the table, `FORCE ROW LEVEL SECURITY`, and per-role policies. App code sets `SET LOCAL app.tenant_id` on every connection checkout; `/db/records` has **no** `WHERE tenant_id` — RLS is the filter.

From `env/dev/workload` after apply:

```bash
eval "$(tofu output -raw helm_install)"
```

That refreshes kubeconfig, waits for nodes, onboards `a` then `b`. Manual equivalent: export `IRSA_A`, `IRSA_B`, `IRSA_MIGRATOR`, `SECRET_A`, `SECRET_B`, `RDS_HOST`, `MASTER_SECRET`, then `./../../../helm/test-app/onboard-tenant.sh a` and `... b`.

### Validation

```bash
ALB="$(tofu output -raw alb_url)"

curl -sS "$ALB/tenant-a/health"    # tenant_id a, database connected
curl -sS "$ALB/tenant-b/health"    # tenant_id b
curl -sS "$ALB/health"             # 404

curl -sS "$ALB/tenant-a/db/init"   # rls true, force_rls true

curl -sS -X POST "$ALB/tenant-a/db/items" -H 'Content-Type: application/json' -d '{"message":"from-a"}'
curl -sS -X POST "$ALB/tenant-b/db/items" -H 'Content-Type: application/json' -d '{"message":"from-b"}'
curl -sS "$ALB/tenant-a/db/records?limit=5"              # only a
curl -sS "$ALB/tenant-b/db/records?limit=5"              # only b
curl -sS "$ALB/tenant-a/db/records?tenant_id=b&limit=5"  # still a

aws eks describe-addon --cluster-name ntier-dev-eks-cluster --addon-name vpc-cni --region us-east-1 \
  --query 'addon.{status:status,config:configurationValues}' --output json
# status ACTIVE, config includes enableNetworkPolicy. Query addon.status — a top-level status is always null.
# aws-node should be 2/2 (policy sidecar).

kubectl run netcheck -n tenant-b --rm -it --image=busybox --restart=Never -- \
  wget -qO- --timeout=3 http://test-app.tenant-a.svc.cluster.local:8080/health
# pass: download timed out

kubectl -n tenant-a scale deploy/test-app --replicas=3
kubectl -n tenant-a get deploy test-app   # 2/3; extra pod never created (quota admission)
kubectl -n tenant-a scale deploy/test-app --replicas=1
```

Logs are JSON on stdout (`tenant_id`, `path`, `status`). There is no Fluent Bit on this cluster. Sample Insights query **after** you ship logs to `/ntier-dev/app`:

```
fields @timestamp, @message
| filter @message like /"msg": "request"/
| parse @message '"tenant_id": "*" ' as tenant
| stats count(*) by tenant, bin(1h)
```

## License

Apache 2.0. See [LICENSE](LICENSE).
