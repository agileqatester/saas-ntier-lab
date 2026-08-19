data "terraform_remote_state" "network" {
  backend = "local"

  config = {
    path = "${path.module}/../network/terraform.tfstate"
  }
}

module "nat" {
  source = "../../../modules/nat"

  name_prefix       = var.name_prefix
  vpc_id            = data.terraform_remote_state.network.outputs.vpc_id
  vpc_cidr          = var.vpc_cidr
  public_subnet_ids = data.terraform_remote_state.network.outputs.public_subnet_ids
  nat_mode          = "instance"
  nat_instance_type = var.nat_instance_type
  enable_ssm        = true
}

resource "aws_route" "private_default" {
  count = length(data.terraform_remote_state.network.outputs.private_route_table_ids)

  route_table_id         = data.terraform_remote_state.network.outputs.private_route_table_ids[count.index]
  destination_cidr_block = "0.0.0.0/0"
  network_interface_id   = module.nat.nat_instance_primary_network_interface_id
}

module "eks" {
  source = "../../../modules/eks"

  name_prefix        = var.name_prefix
  vpc_id             = data.terraform_remote_state.network.outputs.vpc_id
  vpc_cidr           = var.vpc_cidr
  private_subnet_ids = data.terraform_remote_state.network.outputs.private_subnet_ids
  public_subnet_ids  = data.terraform_remote_state.network.outputs.public_subnet_ids
  node_subnet_ids    = [data.terraform_remote_state.network.outputs.private_subnet_ids[0]]

  api_allowed_cidrs  = [var.my_ip]
  kubernetes_version = var.kubernetes_version
  instance_types     = [var.eks_node_instance_type]
  capacity_type      = "ON_DEMAND"
  desired_capacity   = 1
  min_capacity       = 1
  max_capacity       = 1

  depends_on = [aws_route.private_default]
}

module "rds" {
  count  = var.enable_rds ? 1 : 0
  source = "../../../modules/rds"

  name_prefix           = var.name_prefix
  vpc_id                = data.terraform_remote_state.network.outputs.vpc_id
  private_subnet_ids    = data.terraform_remote_state.network.outputs.private_subnet_ids
  eks_security_group_id = module.eks.cluster_security_group_id
  extra_security_group_ids = {
    nat = module.nat.nat_instance_security_group_id
  }
  environment           = "dev"
  instance_class        = var.rds_instance_class
  multi_az              = false
  backup_retention_days = 0
  create_jumpbox_rule   = false
}
