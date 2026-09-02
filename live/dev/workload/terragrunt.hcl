include "root" {
  path   = find_in_parent_folders("root.hcl")
  expose = true
}

locals {
  cfg  = include.root.locals.cfg
  repo = get_repo_root()

  # Required for plan/apply/destroy. CI sets a dummy /32. Never commit this value.
  #   export MY_IP="$(curl -sS https://checkip.amazonaws.com)/32"
  my_ip = get_env("MY_IP")
}

# Wiring from YAML `units.workload.depends_on`. mock_outputs let validate/plan
# run in CI without reading real state or requiring AWS.
dependency "network" {
  config_path = "../${local.cfg.units.workload.depends_on}"

  mock_outputs_allowed_terraform_commands = ["init", "validate", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"

  mock_outputs = {
    vpc_id                  = "vpc-00000000000000000"
    public_subnet_ids       = ["subnet-aaaa", "subnet-bbbb"]
    private_subnet_ids      = ["subnet-cccc", "subnet-dddd"]
    private_route_table_ids = ["rtb-aaaa", "rtb-bbbb"]
  }
}

terraform {
  source = "${get_repo_root()}/${local.cfg.units.workload.terraform}"
}

inputs = merge(
  {
    aws_region  = local.cfg.metadata.aws_region
    name_prefix = local.cfg.metadata.name_prefix
    vpc_cidr    = local.cfg.network.vpc_cidr
    my_ip       = local.my_ip

    vpc_id                  = dependency.network.outputs.vpc_id
    public_subnet_ids       = dependency.network.outputs.public_subnet_ids
    private_subnet_ids      = dependency.network.outputs.private_subnet_ids
    private_route_table_ids = dependency.network.outputs.private_route_table_ids

    helm_test_app_chart   = "${local.repo}/${local.cfg.workload.helm.test_app}"
    helm_fluent_bit_chart = "${local.repo}/${local.cfg.workload.helm.fluent_bit}"
    onboard_script        = "${local.repo}/${local.cfg.workload.helm.onboard}"
  },
  {
    nat_instance_type      = local.cfg.workload.nat_instance_type
    kubernetes_version     = local.cfg.workload.kubernetes_version
    eks_node_instance_type = local.cfg.workload.eks_node_instance_type
    rds_instance_class     = local.cfg.workload.rds_instance_class
    enable_alb             = local.cfg.workload.enable_alb
    enable_rds             = local.cfg.workload.enable_rds
    tenant_ids             = local.cfg.workload.tenant_ids
  }
)
