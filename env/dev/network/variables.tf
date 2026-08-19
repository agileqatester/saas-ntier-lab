variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Name prefix for resources (also used as Project tag)"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR. Used from Stage 2."
  type        = string
  default     = "10.0.0.0/16"
}

variable "azs" {
  description = "Availability zones. Dev compute uses the first AZ only."
  type        = list(string)
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs, one per AZ in azs"
  type        = list(string)
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs, one per AZ in azs"
  type        = list(string)
}
