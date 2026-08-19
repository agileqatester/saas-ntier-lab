variable "name_prefix" {
  description = "Prefix for naming resources"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs (EKS control plane needs at least two AZs)"
  type        = list(string)
}

variable "public_subnet_ids" {
  description = "Public subnet IDs (tagged for a later internet-facing ALB)"
  type        = list(string)
  default     = []
}

variable "node_subnet_ids" {
  description = "Subnets for the managed node group. Empty = all private subnets. Dev: pass the first private subnet only."
  type        = list(string)
  default     = []
}

variable "jumpbox_security_group_id" {
  description = "Optional jumpbox SG allowed to reach the private API. Null in SSM-only Dev."
  type        = string
  default     = null
}

variable "endpoint_public_access" {
  description = "Expose the Kubernetes API on a public endpoint (restricted by api_allowed_cidrs)"
  type        = bool
  default     = true
}

variable "api_allowed_cidrs" {
  description = "CIDRs allowed to call the public EKS API. Dev: your public /32."
  type        = list(string)
  default     = []

  validation {
    condition     = !var.endpoint_public_access || length(var.api_allowed_cidrs) > 0
    error_message = "api_allowed_cidrs must be set when endpoint_public_access is true (your public IP /32)."
  }
}

variable "instance_types" {
  description = "EC2 instance types for the EKS node group"
  type        = list(string)
  default     = ["t4g.small"]
}

variable "ami_type" {
  description = "AMI type for the managed node group"
  type        = string
  default     = "AL2023_ARM_64_STANDARD"

  validation {
    condition = contains([
      "AL2_ARM_64",
      "AL2_x86_64",
      "AL2023_ARM_64_STANDARD",
      "AL2023_x86_64_STANDARD",
      "BOTTLEROCKET_ARM_64",
      "BOTTLEROCKET_x86_64",
    ], var.ami_type)
    error_message = "ami_type must be a valid EKS managed node group AMI."
  }
}

variable "capacity_type" {
  description = "EKS capacity type: ON_DEMAND or SPOT. Dev uses ON_DEMAND so a single AZ is not blocked by Spot capacity."
  type        = string
  default     = "ON_DEMAND"
}

variable "desired_capacity" {
  description = "Desired node count"
  type        = number
  default     = 1
}

variable "min_capacity" {
  description = "Minimum node count"
  type        = number
  default     = 1
}

variable "max_capacity" {
  description = "Maximum node count"
  type        = number
  default     = 1
}

variable "kubernetes_version" {
  description = "Kubernetes version. Must be in EKS standard support ($0.10/hour), not extended ($0.60/hour)."
  type        = string
  default     = "1.35"
}

variable "enable_node_ssm" {
  description = "Attach AmazonSSMManagedInstanceCore to worker nodes (no SSH)"
  type        = bool
  default     = true
}

variable "enable_network_policy" {
  description = "VPC CNI NetworkPolicy (required for Helm NetworkPolicy to enforce). Import the existing vpc-cni addon before first apply."
  type        = bool
  default     = true
}
