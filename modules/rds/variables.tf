variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs"
  type        = list(string)
}

variable "eks_security_group_id" {
  description = "Security group ID of EKS workers / cluster SG (Postgres ingress)"
  type        = string
}

variable "extra_security_group_ids" {
  description = "Additional SGs allowed to reach Postgres. Map keys must be static (e.g. nat); values may be apply-time IDs."
  type        = map(string)
  default     = {}
}

variable "db_username" {
  description = "Master DB username"
  type        = string
  default     = "postgres"
}

variable "db_name" {
  description = "Initial database name"
  type        = string
  default     = "postgres"
}

variable "engine_version" {
  description = "PostgreSQL major version. The module picks the latest matching RDS engine."
  type        = string
  default     = "16"
}

variable "instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t4g.micro"
}

variable "allocated_storage" {
  description = "Allocated storage in GB"
  type        = number
  default     = 20
}

variable "multi_az" {
  description = "Multi-AZ. False for Dev (single instance, cheaper)."
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  description = "Automated backup retention. 0 disables backups (Dev destroy-daily)."
  type        = number
  default     = 0
}

variable "backup_window" {
  description = "The daily time range (in UTC) during which automated backups are created"
  type        = string
  default     = "03:00-05:00"
}

variable "jumpbox_security_group_id" {
  description = "Security group ID of the jumpbox for DB access (optional). If provided, RDS module will create an ingress rule allowing Postgres from this SG."
  type        = string
  default     = ""
}

variable "create_jumpbox_rule" {
  description = "When true, create a security group rule to allow the jumpbox SG to talk to RDS. This avoids depending on across-module computed values at plan time."
  type        = bool
  default     = false
}

variable "sns_topic_arn" {
  description = "SNS topic for CloudWatch alarms. Empty skips the alarm (Dev)."
  type        = string
  default     = ""
}

variable "rds_instance_id" {
  description = "Optional RDS instance identifier to use for alarms; if empty, the created primary instance identifier will be used"
  type        = string
  default     = ""
}

variable "environment" {
  description = "Environment name (e.g., dev, prod) - used to determine deletion protection and snapshot settings"
  type        = string
  default     = "dev"
}

variable "common_tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
  default     = {}
}