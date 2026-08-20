variable "name_prefix" {
  description = "Prefix for naming resources"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "public_subnet_ids" {
  description = "List of public subnet IDs"
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_ids) > 0
    error_message = "At least one public subnet must be provided."
  }
}

variable "acm_certificate_arn" {
  description = "ARN of the ACM certificate for HTTPS (optional if enable_https is false)"
  type        = string
  default     = ""
}

variable "enable_https" {
  description = "Enable HTTPS listener (requires ACM certificate)"
  type        = bool
  default     = true
}

variable "enable_http" {
  description = "Enable HTTP listener (useful for development without SSL certificate)"
  type        = bool
  default     = false
}

variable "http_redirect_to_https" {
  description = "Redirect HTTP to HTTPS (only works if both are enabled)"
  type        = bool
  default     = true
}

variable "route53_zone_id" {
  description = "ID of the Route 53 hosted zone (optional - leave empty to use ALB DNS name directly)"
  type        = string
  default     = ""
}

variable "subdomain_name" {
  description = "Subdomain name to assign to the ALB (e.g., app.example.com). Only used if route53_zone_id is provided."
  type        = string
  default     = ""
}

variable "common_tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "ingress_cidrs" {
  description = "CIDRs allowed to reach the ALB. Dev: your /32. SaaS prod: 0.0.0.0/0."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "target_port" {
  description = "Port on the target (NodePort for EKS instance targets, or container port for IP targets)"
  type        = number
  default     = 80
}

variable "health_check_path" {
  type    = string
  default = "/"
}

variable "target_type" {
  description = "instance (EKS NodePort + ASG) or ip (pods / AWS LB controller)"
  type        = string
  default     = "instance"
}

variable "access_logs_bucket" {
  description = "S3 bucket name for ALB access logs. Empty disables logs."
  type        = string
  default     = ""
}

variable "access_logs_prefix" {
  type    = string
  default = "alb"
}

variable "path_target_groups" {
  description = "HTTP path routing to extra instance TGs (e.g. /tenant-a* → NodePort 30080). Empty keeps a single default TG."
  type = map(object({
    path_pattern = string
    target_port  = number
    priority     = number
  }))
  default = {}
}

variable "fixed_response_body" {
  description = "HTTP 404 body when path_target_groups is set (listener default action)."
  type        = string
  default     = "use /tenant-a/ or /tenant-b/"
}
