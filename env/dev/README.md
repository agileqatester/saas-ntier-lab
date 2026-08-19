# Dev environment

Do **not** run OpenTofu in this directory. Use the stacks:

| Directory | Habit | Cost while left on |
|-----------|--------|--------------------|
| [network/](network/) | `tofu apply` once; keep | ~$0 (VPC/subnets/IGW) + ~$1 if remote state/KMS |
| [workload/](workload/) | `tofu apply` for a test; `tofu destroy` after | NAT, EKS, ALB, optional RDS |

After RDS: `helm/test-app/onboard-tenant.sh` (k8s half; IAM is OpenTofu `for_each`). Paths `/tenant-a*` and `/tenant-b*` on the ALB. Steps and checks: root [README — Pooled tenants](../../README.md#pooled-tenants).

```bash
cp network/terraform.tfvars.example network/terraform.tfvars
# edit name_prefix if you want

cd network
tofu init
tofu plan -var-file=terraform.tfvars
# Stage 2+: tofu apply -var-file=terraform.tfvars
```

CLI is **OpenTofu** (`tofu`). `terraform` as an alias to `tofu` is fine locally.

Root `main.tf` and `env/prod` are the old apply path. Do not use them for new work.
