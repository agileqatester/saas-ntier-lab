include "root" {
  path   = find_in_parent_folders("root.hcl")
  expose = true
}

locals {
  cfg = include.root.locals.cfg
}

terraform {
  source = "${get_repo_root()}/${local.cfg.units.network.terraform}"
}

inputs = merge(
  {
    aws_region  = local.cfg.metadata.aws_region
    name_prefix = local.cfg.metadata.name_prefix
  },
  local.cfg.network
)
