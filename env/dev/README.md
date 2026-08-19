# Dev environment

Do **not** apply in this directory. Use the stacks:

| Directory | Habit | Cost while left on |
|-----------|--------|--------------------|
| [network/](network/) | apply once; keep | ~$0 (VPC/subnets/IGW) + ~$1 if remote state/KMS |
| [workload/](workload/) | apply for a test; destroy after | NAT, EKS, ALB, optional RDS |

```bash
cp network/terraform.tfvars.example network/terraform.tfvars
# edit name_prefix if you want

cd network
tofu init
tofu plan -var-file=terraform.tfvars
tofu apply -var-file=terraform.tfvars
```

CLI is OpenTofu (`tofu`) or HashiCorp Terraform (`terraform`).
