# Composition modules (catalog)

These are OpenTofu modules that **compose** the primitive modules in `modules/{vpc,nat,eks,rds,alb}`. They have no `provider` or `backend` — Terragrunt generates those in `live/`.

| Module | Live unit | Notes |
|--------|-----------|--------|
| `network` | `live/dev/network` | VPC only. Keep applied. |
| `workload` | `live/dev/workload` | NAT, EKS, ALB, optional RDS. Destroy after tests. |

Do not `tofu apply` here. Values and module paths live in `live/dev/config.yaml`. Network outputs are passed into workload via a Terragrunt `dependency` block (no `terraform_remote_state`).

Helm chart paths are **inputs** (`helm_test_app_chart`, …) because Terragrunt runs OpenTofu from `.terragrunt-cache`.
