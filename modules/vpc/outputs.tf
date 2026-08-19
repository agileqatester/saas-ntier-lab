output "vpc_id" {
  description = "ID of the created VPC"
  value       = aws_vpc.this.id
}

output "igw_id" {
  description = "Internet Gateway ID"
  value       = aws_internet_gateway.this.id
}

output "public_subnet_ids" {
  description = "IDs of public subnets"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "IDs of private subnets"
  value       = aws_subnet.private[*].id
}

output "public_route_table_id" {
  description = "Public route table ID"
  value       = aws_route_table.public.id
}

output "private_route_table_ids" {
  description = "Private route table IDs (one per AZ)"
  value       = aws_route_table.private[*].id
}

output "nat_gateway_ids" {
  description = "NAT gateway IDs (empty when nat_mode is none)"
  value       = try(module.nat[0].nat_gateway_ids, [])
}

output "vpc_endpoint_ids" {
  description = "VPC endpoint IDs. Interface endpoints are empty when disabled."
  value = {
    s3             = aws_vpc_endpoint.s3_gateway.id
    kinesis        = try(aws_vpc_endpoint.kinesis_firehose[0].id, null)
    secretsmanager = try(aws_vpc_endpoint.secretsmanager[0].id, null)
    eks            = try(aws_vpc_endpoint.eks[0].id, null)
    ecr_dkr        = try(aws_vpc_endpoint.ecr_dkr[0].id, null)
    ecr_api        = try(aws_vpc_endpoint.ecr_api[0].id, null)
  }
}

output "endpoint_security_group_id" {
  description = "SG used by interface endpoints, if any"
  value       = var.enable_interface_endpoints ? local.interface_endpoint_sg_id : null
}

output "endpoint_subnet_ids" {
  description = "Dedicated endpoint subnet IDs (empty if none)"
  value       = aws_subnet.endpoint[*].id
}
