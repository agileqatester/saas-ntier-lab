output "nat_instance_id" {
  value = module.nat.nat_instance_id
}

output "nat_instance_public_ip" {
  value = module.nat.nat_instance_public_ip
}

output "ssm_start_session" {
  description = "SSM session to the NAT instance (requires session-manager-plugin)"
  value       = "aws ssm start-session --target ${module.nat.nat_instance_id} --region ${var.aws_region}"
}

output "eks_cluster_name" {
  value = module.eks.eks_cluster_name
}

output "eks_cluster_endpoint" {
  value = module.eks.eks_cluster_endpoint
}

output "update_kubeconfig" {
  value = module.eks.update_kubeconfig
}

output "vpc_id" {
  value = data.terraform_remote_state.network.outputs.vpc_id
}

output "vpc_cidr" {
  value = var.vpc_cidr
}

output "public_subnet_cidrs" {
  description = "ALB subnet CIDRs — NetworkPolicy allowlist for target-type ip (not full VPC)."
  value       = [for id in data.terraform_remote_state.network.outputs.public_subnet_ids : data.aws_subnet.public[id].cidr_block]
}

output "private_subnet_cidrs" {
  description = "Private subnet CIDRs — NetworkPolicy egress allowlist for Postgres (RDS ENIs)."
  value       = [for id in data.terraform_remote_state.network.outputs.private_subnet_ids : data.aws_subnet.private[id].cidr_block]
}

output "ingress_mode" {
  value = var.ingress_mode
}

output "alb_ingress_group" {
  description = "alb.ingress.kubernetes.io/group.name for shared ALB"
  value       = var.name_prefix
}

output "name_prefix" {
  value = var.name_prefix
}

output "rds_endpoint" {
  value = var.enable_rds ? module.rds[0].rds_endpoint : null
}

output "rds_host" {
  value = var.enable_rds ? module.rds[0].rds_host : null
}

output "rds_secret_name" {
  description = "Master secret (migrate Job only). Tenant pods use tenant_secret_names."
  value       = var.enable_rds ? module.rds[0].rds_credentials_secret_name : null
}

output "aws_region" {
  value = var.aws_region
}

output "tenant_ids" {
  description = "OpenTofu-managed tenant ids (empty when control plane owns identity)."
  value       = var.manage_tenant_identity ? var.tenant_ids : []
}

output "platform_tenant_id" {
  description = "Tenant id used for the RLS migrate Job namespace."
  value       = local.first_tenant
}

output "manage_tenant_identity" {
  value = var.manage_tenant_identity
}

output "tenant_node_ports" {
  description = "NodePort per tenant when ingress_mode=nodeport. Empty map in alb_controller mode."
  value       = local.tenant_node_ports
}

output "tenant_secret_names" {
  value = var.enable_rds ? { for k, s in aws_secretsmanager_secret.tenant : k => s.name } : {}
}

output "tenant_irsa_role_arns" {
  value = var.enable_rds ? { for k, r in aws_iam_role.tenant : k => r.arn } : {}
}

output "migrator_irsa_role_arn" {
  value = var.enable_rds ? aws_iam_role.migrator[0].arn : null
}

output "test_app_irsa_role_arn" {
  description = "IRSA for platform tenant when OpenTofu manages identity. Null when control plane owns identity."
  value = (
    var.enable_rds && var.manage_tenant_identity
    ? aws_iam_role.tenant[local.first_tenant].arn
    : null
  )
}

output "alb_dns_name" {
  value = local.use_legacy_alb ? module.alb[0].alb_dns_name : (
    fileexists(local.alb_url_file) ? trimprefix(trimsuffix(trimspace(file(local.alb_url_file)), "/"), "http://") : null
  )
}

output "alb_url" {
  description = "Public app URL. Controller mode: written by onboard to .alb_url after Ingress is ready."
  value = local.use_legacy_alb ? module.alb[0].alb_url : (
    fileexists(local.alb_url_file) ? trimspace(file(local.alb_url_file)) : null
  )
}

output "alb_logs_bucket" {
  value = var.enable_alb ? aws_s3_bucket.alb_logs[0].id : null
}

output "sns_alerts_topic_arn" {
  value = var.enable_alb ? aws_sns_topic.alerts[0].arn : null
}

output "lbc_role_arn" {
  value = local.use_controller ? aws_iam_role.lbc[0].arn : null
}

output "oidc_provider_arn" {
  value = module.eks.oidc_provider_arn
}

output "oidc_provider_url" {
  value = module.eks.oidc_provider_url
}

output "app_log_group" {
  value = aws_cloudwatch_log_group.app.name
}

output "helm_install" {
  description = "Onboard var.tenant_ids after nodes are Ready. Uses helm/test-app/onboard_tenant.py"
  value = templatefile("${path.module}/helm_install.tftpl", {
    enable_rds        = var.enable_rds
    use_controller    = local.use_controller
    chart             = "${path.module}/../../../helm/test-app"
    onboard           = "${path.module}/../../../helm/test-app/onboard_tenant.py"
    fluent_chart      = "${path.module}/../../../helm/fluent-bit"
    fluent_bit_role   = aws_iam_role.fluent_bit.arn
    log_group         = aws_cloudwatch_log_group.app.name
    tenant_ids        = length(var.tenant_ids) > 0 ? var.tenant_ids : [var.platform_tenant_id]
    first_tenant      = local.first_tenant
    first_node_port   = try(local.tenant_node_ports[local.first_tenant], 30080)
    region            = var.aws_region
    cluster_name      = module.eks.eks_cluster_name
    vpc_id            = data.terraform_remote_state.network.outputs.vpc_id
    lbc_role_arn      = try(aws_iam_role.lbc[0].arn, "")
    alb_ingress_group = var.name_prefix
    alb_url = local.use_legacy_alb ? module.alb[0].alb_url : (
      fileexists(local.alb_url_file) ? trimspace(file(local.alb_url_file)) : "http://127.0.0.1:8080"
    )
  })
}
