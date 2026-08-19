variable "aws_region" {
  description = "AWS region (must match the network stack)"
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Must match the network stack name_prefix"
  type        = string
}

variable "vpc_cidr" {
  description = "Must match the network VPC CIDR (used in the NAT security group)"
  type        = string
  default     = "10.0.0.0/16"
}

variable "nat_instance_type" {
  description = "NAT instance size. t4g.nano is cheapest for Dev."
  type        = string
  default     = "t4g.nano"
}

variable "my_ip" {
  description = "Laptop public IP as x.x.x.x/32 for the EKS API and ALB HTTP. Pass at apply with -var. Do not commit it."
  type        = string
  sensitive   = true

  validation {
    condition     = can(cidrhost(var.my_ip, 0)) && endswith(var.my_ip, "/32")
    error_message = "my_ip must be a single host CIDR (x.x.x.x/32)."
  }
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version. Stay on standard support ($0.10/hour)."
  type        = string
  default     = "1.35"
}

variable "eks_node_instance_type" {
  description = "Single Dev node. t4g.small: t4g.micro only allows 4 pods (CNI) so the app cannot schedule."
  type        = string
  default     = "t4g.small"
}

variable "rds_instance_class" {
  description = "Single-AZ Postgres. db.t4g.micro is cheapest for Dev."
  type        = string
  default     = "db.t4g.micro"
}

variable "enable_rds" {
  description = "Postgres + per-tenant secrets/IRSA + migrator role. Default false (ALB session). Set true in terraform.tfvars, apply, then re-run tofu output -raw helm_install."
  type        = bool
  default     = false
}

variable "enable_alb" {
  description = "Internet-facing HTTP ALB. Path rules /tenant-a* and /tenant-b* (NodePorts 30080/30081). Ingress is var.my_ip. Default action 404."
  type        = bool
  default     = true
}
