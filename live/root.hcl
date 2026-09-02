# Shared Terragrunt config for every live unit.
# Units include this file; do not run Terragrunt from this directory.
# Values come from config.yaml next to the units (see live/dev/config.yaml).

terraform_binary              = "tofu"
terragrunt_version_constraint = ">= 1.0.0"
terraform_version_constraint  = ">= 1.6.0"

locals {
  config_file = find_in_parent_folders("config.yaml")
  local_file  = "${dirname(local.config_file)}/config.local.yaml"
  base        = yamldecode(file(local.config_file))
  overlay     = fileexists(local.local_file) ? yamldecode(file(local.local_file)) : {}

  metadata = merge(local.base.metadata, try(local.overlay.metadata, {}))
  units    = merge(local.base.units, try(local.overlay.units, {}))
  network  = merge(local.base.network, try(local.overlay.network, {}))
  workload = merge(
    local.base.workload,
    try(local.overlay.workload, {}),
    {
      helm = merge(local.base.workload.helm, try(local.overlay.workload.helm, {}))
    }
  )

  # What every unit reads via include.root.locals.cfg
  cfg = {
    metadata = local.metadata
    units    = local.units
    network  = local.network
    workload = local.workload
  }

  backend_file     = "${get_parent_terragrunt_dir()}/backend.hcl"
  use_remote_state = fileexists(local.backend_file)
  backend          = local.use_remote_state ? read_terragrunt_config(local.backend_file).locals : null

  # Matches the old stack keys so a later migrate-state lands on the same objects.
  state_key = "ntier-app/${path_relative_to_include()}/terraform.tfstate"
}

# Provider is generated into the cache copy so catalog modules stay provider-free.
generate "provider" {
  path      = "provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "${local.metadata.aws_region}"

  default_tags {
    tags = {
      Environment = "${local.metadata.environment}"
      Project     = "${local.metadata.name_prefix}"
      ManagedBy   = "Terragrunt"
      Stack       = "${basename(get_terragrunt_dir())}"
    }
  }
}
EOF
}

# Local until you copy backend.hcl.example → backend.hcl (gitignored).
# When S3 is enabled, skip Terragrunt's bucket/table auto-create: bootstrap/ owns
# those resources (KMS, public-access block, versioning, lifecycle).
remote_state {
  backend = local.use_remote_state ? "s3" : "local"
  generate = {
    path      = "backend.tf"
    if_exists = "overwrite_terragrunt"
  }
  config = local.use_remote_state ? {
    bucket         = local.backend.bucket
    key            = local.state_key
    region         = local.backend.region
    dynamodb_table = local.backend.dynamodb_table
    encrypt        = true
    kms_key_id     = local.backend.kms_key_id

    skip_bucket_creation               = true
    skip_bucket_versioning             = true
    skip_bucket_ssencryption           = true
    skip_bucket_root_access            = true
    skip_bucket_enforced_tls           = true
    skip_bucket_public_access_blocking = true
    skip_bucket_accesslogging          = true
    disable_bucket_update              = true
    } : {
    path = "${get_parent_terragrunt_dir()}/.terraform-state/${path_relative_to_include()}/terraform.tfstate"
  }
}

terraform {
  extra_arguments "no_input" {
    commands  = ["init", "plan", "apply", "destroy", "refresh", "import"]
    arguments = ["-input=false"]
  }

  extra_arguments "parallelism" {
    commands  = ["plan", "apply", "destroy"]
    arguments = ["-parallelism=10"]
  }
}
