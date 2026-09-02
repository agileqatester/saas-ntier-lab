# Dev (Terragrunt)

Do **not** run Terragrunt in this directory except `run --all` from here. Prefer the units:

| Directory | Habit |
|-----------|--------|
| [network/](network/) | keep (free VPC) |
| [workload/](workload/) | destroy after each test |

Shared non-secret values and HCL module paths: [config.yaml](config.yaml). Laptop-only flags: `config.local.yaml` (gitignored). Laptop IP: `MY_IP`.

See [live/README.md](../README.md) and the root README.
