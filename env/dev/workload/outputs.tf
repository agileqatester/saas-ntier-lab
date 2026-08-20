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
  value = var.tenant_ids
}

output "tenant_node_ports" {
  description = "NodePort per tenant (30080 + index in tenant_ids). Must match Helm."
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
  description = "IRSA for the first tenant_ids entry (compat). Prefer tenant_irsa_role_arns."
  value       = var.enable_rds ? aws_iam_role.tenant[local.first_tenant].arn : null
}

output "alb_dns_name" {
  value = var.enable_alb ? module.alb[0].alb_dns_name : null
}

output "alb_url" {
  value = var.enable_alb ? module.alb[0].alb_url : null
}

output "alb_logs_bucket" {
  value = var.enable_alb ? aws_s3_bucket.alb_logs[0].id : null
}

output "sns_alerts_topic_arn" {
  value = var.enable_alb ? aws_sns_topic.alerts[0].arn : null
}

output "app_log_group" {
  value = aws_cloudwatch_log_group.app.name
}

output "helm_install" {
  description = "Onboard var.tenant_ids after nodes are Ready. Uses helm/test-app/onboard_tenant.py"
  value = templatefile("${path.module}/helm_install.tftpl", {
    enable_rds      = var.enable_rds
    chart           = "${path.module}/../../../helm/test-app"
    onboard         = "${path.module}/../../../helm/test-app/onboard_tenant.py"
    fluent_chart    = "${path.module}/../../../helm/fluent-bit"
    fluent_bit_role = aws_iam_role.fluent_bit.arn
    log_group       = aws_cloudwatch_log_group.app.name
    tenant_ids      = var.tenant_ids
    first_tenant    = local.first_tenant
    first_node_port = local.tenant_node_ports[local.first_tenant]
    region          = var.aws_region
    cluster_name    = module.eks.eks_cluster_name
    alb_url         = try(module.alb[0].alb_url, "http://127.0.0.1:8080")
  })
}
