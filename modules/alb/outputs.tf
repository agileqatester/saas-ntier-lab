output "alb_dns_name" {
  description = "DNS name of the ALB"
  value       = aws_lb.this.dns_name
}

output "alb_security_group_id" {
  description = "Security Group ID attached to the ALB"
  value       = aws_security_group.alb.id
}

output "alb_fqdn" {
  description = "Fully qualified domain name (FQDN) for the ALB using Route 53 (empty if Route53 not configured)"
  value       = var.route53_zone_id != "" && var.subdomain_name != "" ? try(aws_route53_record.alb_dns[0].fqdn, "") : ""
}

output "alb_url" {
  description = "URL to access the ALB (uses Route53 FQDN if available, otherwise ALB DNS name)"
  value       = var.route53_zone_id != "" && var.subdomain_name != "" ? "https://${try(aws_route53_record.alb_dns[0].fqdn, "")}" : "http://${aws_lb.this.dns_name}"
}

output "http_target_group_arn" {
  value = try(aws_lb_target_group.http[0].arn, "")
}

output "alb_arn" {
  value = aws_lb.this.arn
}

output "alb_arn_suffix" {
  description = "For CloudWatch dimensions (app/name/id)"
  value       = aws_lb.this.arn_suffix
}
