output "rds_primary_endpoint" {
  description = "Primary RDS instance endpoint"
  value       = aws_db_instance.primary.endpoint
}



output "rds_credentials_secret_name" {
  description = "Name of the one Secrets Manager secret (username/password/host)"
  value       = aws_secretsmanager_secret.db.name
}

output "rds_credentials_secret_arn" {
  description = "ARN of the Secrets Manager secret containing RDS credentials"
  value       = aws_secretsmanager_secret.db.arn
}

output "rds_host" {
  value = aws_db_instance.primary.address
}

output "rds_endpoint" {
  description = "The endpoint of the primary RDS instance"
  value       = aws_db_instance.primary.endpoint
}

output "rds_security_group_id" {
  value = aws_security_group.rds.id
}

output "rds_instance_id" {
  value = aws_db_instance.primary.id
}