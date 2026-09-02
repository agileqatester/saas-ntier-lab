# How to apply

Apply from **Terragrunt live units**, not the repo root and not `modules/`.

```bash
cd live/dev/network
terragrunt apply

export MY_IP="$(curl -sS https://checkip.amazonaws.com)/32"
cd ../workload
terragrunt apply
terragrunt destroy
```

`env/` used to hold OpenTofu stacks; those compositions now live in `modules/stacks/` and are driven from `live/`. See [live/README.md](../live/README.md).
