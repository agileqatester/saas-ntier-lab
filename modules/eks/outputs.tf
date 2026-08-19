output "eks_cluster_name" {
  description = "Name of the EKS cluster"
  value       = aws_eks_cluster.this.name
}

output "cluster_name" {
  value = aws_eks_cluster.this.name
}

output "eks_cluster_endpoint" {
  description = "Endpoint URL of the EKS cluster"
  value       = aws_eks_cluster.this.endpoint
}

output "eks_cluster_security_group_id" {
  description = "Extra SG attached to the control plane ENIs"
  value       = aws_security_group.eks.id
}

output "cluster_security_group_id" {
  description = "AWS-managed cluster SG (on nodes; use this for RDS ingress)"
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}

output "eks_node_group_name" {
  description = "Name of the EKS managed node group"
  value       = aws_eks_node_group.this.node_group_name
}

output "eks_node_role_arn" {
  description = "IAM role ARN used by EKS worker nodes"
  value       = aws_iam_role.eks_node.arn
}

output "eks_cluster_role_arn" {
  description = "IAM role ARN used by EKS control plane"
  value       = aws_iam_role.eks_cluster.arn
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.this.arn
}

output "oidc_provider_url" {
  value = replace(aws_eks_cluster.this.identity[0].oidc[0].issuer, "https://", "")
}

output "update_kubeconfig" {
  description = "Configure kubectl for this cluster (IAM identity that created it is cluster-admin)"
  value       = "aws eks update-kubeconfig --name ${aws_eks_cluster.this.name} --region ${data.aws_region.current.name}"
}

output "node_group_asg_name" {
  description = "ASG backing the managed node group (ALB instance targets)"
  value       = try(aws_eks_node_group.this.resources[0].autoscaling_groups[0].name, "")
}