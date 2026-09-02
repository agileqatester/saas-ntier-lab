# Live units (Terragrunt)

This directory is the **only apply path** for Dev. OpenTofu modules live under `modules/`; bootstrap (S3/DynamoDB/KMS) stays plain OpenTofu because it has to exist before remote state.

**Config is YAML.** [dev/config.yaml](dev/config.yaml) holds every non-secret value and the path to each HCL composition module. The `terragrunt.hcl` files in `network/` and `workload/` only read that YAML, set `terraform.source`, and wire dependencies.

| Unit | Habit | Cost while left on |
|------|--------|--------------------|
| [dev/network](dev/network) | `terragrunt apply` once; keep | ~$0 (VPC/subnets/IGW) + ~$1 if remote state/KMS |
| [dev/workload](dev/workload) | apply for a test; destroy after | NAT, EKS, ALB, optional RDS |

```bash
# Prerequisites: OpenTofu >= 1.6, Terragrunt >= 1.0, AWS creds.
# Never commit backend.hcl, config.local.yaml, or MY_IP.

cd live/dev/network
terragrunt apply

export MY_IP="$(curl -sS https://checkip.amazonaws.com)/32"
cd ../workload
terragrunt apply
# destroy paid resources; leave network:
terragrunt destroy
```

`cd live/dev && terragrunt run --all -- apply` also works (network first). Destroy of `--all` is **not** the Dev habit — that would delete the VPC. Destroy **workload** only.

## Remote state

Local state is the default (gitignored under `live/.terraform-state/`). After `bootstrap/`:

```bash
cp live/backend.hcl.example live/backend.hcl
# set bucket, dynamodb_table, kms_key_id from: cd bootstrap && tofu output
```

Terragrunt is configured **not** to create or mutate that bucket. Keys stay `ntier-app/dev/<unit>/terraform.tfstate`.

## Overrides

Copy `dev/config.local.yaml.example` to `dev/config.local.yaml` for `enable_rds` / extra `tenant_ids`. Do not put `my_ip` there — use `MY_IP`.
