variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "azs" {
  type        = list(string)
  default     = []
  description = "Used only when nat_mode is gateway (one NAT GW per AZ). Ignored for instance."
}

variable "nat_mode" {
  type        = string
  default     = "instance"
  description = "NAT mode: gateway (AWS managed) or instance (EC2 NAT with IMDSv2/SSM)"

  validation {
    condition     = contains(["gateway", "instance"], var.nat_mode)
    error_message = "nat_mode must be gateway or instance"
  }
}

variable "vpc_cidr" {
  type        = string
  default     = "10.0.0.0/16"
  description = "VPC CIDR allowed to send traffic through the NAT instance"
}

variable "enable_ssm" {
  type        = bool
  default     = true
  description = "Attach SSM instance profile (no SSH). Dev ops access via Session Manager."
}

variable "nat_instance_ami" {
  type    = string
  default = ""
}

variable "nat_instance_type" {
  type        = string
  default     = "t4g.nano"
  description = "Instance type for NAT instance (t4g.nano = ~$3.80/month, t4g.micro = ~$7.60/month)"
}
