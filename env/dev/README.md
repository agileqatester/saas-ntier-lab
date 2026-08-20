# Dev environment

Do **not** run OpenTofu in this directory. Use the stacks:

| Directory | Habit | Cost while left on |
|-----------|--------|--------------------|
| [network/](network/) | `tofu apply` once; keep | ~$0 (VPC/subnets/IGW) + ~$1 if remote state/KMS |
| [workload/](workload/) | `tofu apply` for a test; `tofu destroy` after | NAT, EKS, ALB, optional RDS |

After RDS: add tenants with OpenTofu `tenant_ids` then `onboard_tenant.py` (see root [README — Add a tenant](../../README.md#add-a-tenant)). IAM is OpenTofu `for_each`; the script reads `tofu output -json`.

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
