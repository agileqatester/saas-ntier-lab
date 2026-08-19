# How to apply

Apply from a **stack directory**, not the repo root and not `env/dev/` itself. The HCL is Terraform; commands below use OpenTofu (`tofu`). `terraform` is the same workflow.

```bash
cd env/dev/network    # keep (free VPC)
tofu init
tofu plan -var-file=terraform.tfvars

cd ../workload        # destroy after each test (NAT / EKS / ALB; RDS off unless enable_rds)
tofu init
tofu plan -var-file=terraform.tfvars \
  -var="my_ip=$(curl -s https://checkip.amazonaws.com)/32"
tofu destroy -var-file=terraform.tfvars \
  -var="my_ip=$(curl -s https://checkip.amazonaws.com)/32"
```

Copy `terraform.tfvars.example` to `terraform.tfvars` in that directory first (`*.tfvars` is gitignored).
