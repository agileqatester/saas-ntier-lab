variable "name_prefix" {
  description = "Prefix for naming AWS resources"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr))
    error_message = "vpc_cidr must be a valid CIDR block"
  }
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs (same length as azs)"
  type        = list(string)
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs (same length as azs)"
  type        = list(string)
}

variable "azs" {
  description = "Availability zones"
  type        = list(string)

  validation {
    condition     = length(var.azs) > 0
    error_message = "azs must be a non-empty list"
  }
}

variable "region" {
  description = "AWS region (used for VPC endpoint service names)"
  type        = string
}

variable "nat_mode" {
  description = "NAT for private subnets: none (no NAT, no default route), gateway, instance, or custom. none is the Dev keep-stack default (NAT lives in the workload stack)."
  type        = string
  default     = "none"

  validation {
    condition     = contains(["none", "gateway", "instance", "custom"], var.nat_mode)
    error_message = "nat_mode must be none, gateway, instance, or custom"
  }
}

variable "nat_instance_ami" {
  description = "Optional AMI for NAT instance when nat_mode is instance"
  type        = string
  default     = ""
}

variable "enable_interface_endpoints" {
  description = "Create paid interface VPC endpoints (ECR, EKS, Secrets Manager, Kinesis). Off in Dev; S3 gateway endpoint is always created and is free."
  type        = bool
  default     = false
}

variable "endpoint_subnet_cidrs" {
  description = "Optional dedicated subnets for interface endpoints. Empty = place them in private subnets."
  type        = list(string)
  default     = []
}

variable "endpoint_security_group_id" {
  description = "Optional SG for interface endpoints. Empty = create one in this module."
  type        = string
  default     = ""
}

variable "vpc_cidr_blocks" {
  description = "Unused leftover; kept so older callers do not break. Prefer vpc_cidr."
  type        = list(string)
  default     = []
}

variable "enable_ipv6" {
  description = "Unused; IPv6 is not implemented."
  type        = bool
  default     = false
}
