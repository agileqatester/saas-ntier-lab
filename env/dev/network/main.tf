module "vpc" {
  source = "../../../modules/vpc"

  name_prefix = var.name_prefix
  region      = var.aws_region
  vpc_cidr    = var.vpc_cidr
  azs         = var.azs

  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs

  # Keep-stack: no NAT (paid). Workload stack will add a NAT instance later.
  nat_mode                   = "none"
  enable_interface_endpoints = false
}
