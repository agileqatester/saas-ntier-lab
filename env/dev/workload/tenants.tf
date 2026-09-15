# Pooled tenant keys. IAM/secrets follow local.tenants when manage_tenant_identity.
# Edge routing depends on var.ingress_mode (nodeport vs alb_controller).

locals {
  tenants = (
    var.enable_rds && var.manage_tenant_identity
    ? toset(var.tenant_ids)
    : toset([])
  )
  # Migrate Job / first-tenant semantics: tofu list[0] or explicit platform id.
  first_tenant = (
    var.manage_tenant_identity && length(var.tenant_ids) > 0
    ? var.tenant_ids[0]
    : var.platform_tenant_id
  )
  # IDs used only for legacy NodePort ALB path map (empty in alb_controller mode).
  edge_tenant_ids = (
    length(var.tenant_ids) > 0
    ? var.tenant_ids
    : [var.platform_tenant_id]
  )
  use_controller = var.ingress_mode == "alb_controller"
  use_legacy_alb = var.enable_alb && !local.use_controller
  node_port_base = 30080
  tenant_node_ports = local.use_controller ? {} : {
    for i, tid in local.edge_tenant_ids : tid => local.node_port_base + i
  }
  tenant_path_target_groups = local.use_controller ? {} : {
    for i, tid in local.edge_tenant_ids : tid => {
      path_pattern = "/tenant-${tid}*"
      target_port  = local.tenant_node_ports[tid]
      priority     = (i + 1) * 10
    }
  }
  node_port_min = length(local.tenant_node_ports) > 0 ? min([for p in values(local.tenant_node_ports) : p]...) : 0
  node_port_max = length(local.tenant_node_ports) > 0 ? max([for p in values(local.tenant_node_ports) : p]...) : 0
  alb_404_body  = "use ${join(" or ", [for tid in local.edge_tenant_ids : "/tenant-${tid}/"])}"
  alb_url_file  = "${path.module}/.alb_url"
}
