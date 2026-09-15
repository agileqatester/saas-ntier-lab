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
  description = "NAT instance size. Prefer t4g.micro: t4g.nano often OOMs during cloud-init dnf (iptables never installs)."
  type        = string
  default     = "t4g.micro"
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
  description = "Single Dev node. t4g.small max ~11 pods (tight with 5 tenants). Use t4g.medium for alb_controller mode (~17 pods)."
  type        = string
  default     = "t4g.small"
}

variable "ingress_mode" {
  description = "Product edge: nodeport = OpenTofu ALB + per-tenant NodePort (legacy lab). alb_controller = shared ALB via AWS Load Balancer Controller Ingress (Phase A)."
  type        = string
  default     = "alb_controller"

  validation {
    condition     = contains(["nodeport", "alb_controller"], var.ingress_mode)
    error_message = "ingress_mode must be nodeport or alb_controller."
  }
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

variable "manage_tenant_identity" {
  description = "If true, OpenTofu for_each creates per-tenant SM secrets + IRSA. If false (default), the control plane owns them; use platform_tenant_id for migrate Job."
  type        = bool
  default     = false
}

variable "platform_tenant_id" {
  description = "Tenant id whose namespace runs the RLS migrate Job (usually a). Required when manage_tenant_identity is false."
  type        = string
  default     = "a"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{0,15}$", var.platform_tenant_id))
    error_message = "platform_tenant_id must be a short lowercase label."
  }
}

variable "tenant_ids" {
  description = "When manage_tenant_identity=true: pooled keys OpenTofu creates SM/IRSA for. When false: ignored for identity (control plane owns); may be empty."
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.tenant_ids) == length(toset(var.tenant_ids))
    error_message = "tenant_ids must be unique."
  }
  validation {
    condition     = alltrue([for t in var.tenant_ids : can(regex("^[a-z][a-z0-9]{0,15}$", t))])
    error_message = "each tenant id must be a short lowercase label (e.g. a, b, c)."
  }
  validation {
    condition     = !var.manage_tenant_identity || length(var.tenant_ids) > 0
    error_message = "tenant_ids must be non-empty when manage_tenant_identity is true."
  }
}

variable "enable_alb" {
  description = "Access-logs bucket + SNS. In nodeport mode also creates the OpenTofu ALB. In alb_controller mode the controller owns the ALB; this still creates the logs bucket."
  type        = bool
  default     = true
}
