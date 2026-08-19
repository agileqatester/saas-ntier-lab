output "vpc_id" {
  description = "VPC ID (keep this stack applied)"
  value       = module.vpc.vpc_id
}

output "igw_id" {
  value = module.vpc.igw_id
}

output "public_subnet_ids" {
  value = module.vpc.public_subnet_ids
}

output "private_subnet_ids" {
  value = module.vpc.private_subnet_ids
}

output "private_route_table_ids" {
  description = "Workload NAT will add 0.0.0.0/0 on these tables later"
  value       = module.vpc.private_route_table_ids
}

output "nat_gateway_ids" {
  description = "Must be empty in this stack"
  value       = module.vpc.nat_gateway_ids
}
