# Pooled tenant keys. IAM/secrets follow local.tenants (empty when RDS is off).
# ALB paths and NodePorts follow var.tenant_ids even with RDS off so /tenant-* rules exist.

locals {
  tenants        = var.enable_rds ? toset(var.tenant_ids) : toset([])
  first_tenant   = var.tenant_ids[0]
  node_port_base = 30080
  tenant_node_ports = {
    for i, tid in var.tenant_ids : tid => local.node_port_base + i
  }
  tenant_path_target_groups = {
    for i, tid in var.tenant_ids : tid => {
      path_pattern = "/tenant-${tid}*"
      target_port  = local.tenant_node_ports[tid]
      priority     = (i + 1) * 10
    }
  }
  node_port_min = min([for p in values(local.tenant_node_ports) : p]...)
  node_port_max = max([for p in values(local.tenant_node_ports) : p]...)
  alb_404_body  = "use ${join(" or ", [for tid in var.tenant_ids : "/tenant-${tid}/"])}"
}
