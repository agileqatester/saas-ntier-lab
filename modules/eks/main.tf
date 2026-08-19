data "aws_region" "current" {}

locals {
  cluster_name    = "${var.name_prefix}-eks-cluster"
  node_subnet_ids = length(var.node_subnet_ids) > 0 ? var.node_subnet_ids : var.private_subnet_ids
}

resource "aws_iam_role" "eks_cluster" {
  name = "${var.name_prefix}-eks-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_cluster_AmazonEKSClusterPolicy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.eks_cluster.name
}

resource "aws_security_group" "eks" {
  name        = "${var.name_prefix}-eks-sg"
  description = "Extra SG on the EKS control plane ENIs"
  vpc_id      = var.vpc_id

  ingress {
    description = "Workers and in-VPC clients to the API"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name_prefix}-eks-sg"
  }
}

resource "aws_eks_cluster" "this" {
  name     = local.cluster_name
  role_arn = aws_iam_role.eks_cluster.arn
  version  = var.kubernetes_version

  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = true
  }

  upgrade_policy {
    support_type = "STANDARD"
  }

  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = var.endpoint_public_access
    public_access_cidrs     = var.endpoint_public_access ? var.api_allowed_cidrs : null
    security_group_ids      = [aws_security_group.eks.id]
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_AmazonEKSClusterPolicy
  ]
}

resource "aws_iam_role" "eks_node" {
  name = "${var.name_prefix}-eks-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_worker_node_policies" {
  for_each = toset(concat(
    [
      "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
      "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
      "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    ],
    var.enable_node_ssm ? ["arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"] : []
  ))

  role       = aws_iam_role.eks_node.name
  policy_arn = each.key
}

# Node group tags do not land on the EC2 instance. Tag at launch; AMI/type stay on the node group.
resource "aws_launch_template" "eks_nodes" {
  name_prefix = "${var.name_prefix}-eks-node-"
  description = "Name tag for EKS managed nodes"

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "${var.name_prefix}-eks-node"
    }
  }

  tag_specifications {
    resource_type = "volume"
    tags = {
      Name = "${var.name_prefix}-eks-node"
    }
  }

  tags = {
    Name = "${var.name_prefix}-eks-node-lt"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_eks_node_group" "this" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${var.name_prefix}-eks-nodes"
  node_role_arn   = aws_iam_role.eks_node.arn
  subnet_ids      = local.node_subnet_ids

  scaling_config {
    desired_size = var.desired_capacity
    min_size     = var.min_capacity
    max_size     = var.max_capacity
  }

  instance_types = var.instance_types
  ami_type       = var.ami_type
  capacity_type  = var.capacity_type

  launch_template {
    id      = aws_launch_template.eks_nodes.id
    version = aws_launch_template.eks_nodes.latest_version
  }

  update_config {
    max_unavailable = 1
  }

  tags = {
    Name = "${var.name_prefix}-eks-nodes"
  }

  depends_on = [aws_iam_role_policy_attachment.eks_worker_node_policies]
}

# ASG-level Name so replacements also get it in the console.
resource "aws_autoscaling_group_tag" "eks_node_name" {
  autoscaling_group_name = aws_eks_node_group.this.resources[0].autoscaling_groups[0].name

  tag {
    key                 = "Name"
    value               = "${var.name_prefix}-eks-node"
    propagate_at_launch = true
  }
}

resource "aws_iam_openid_connect_provider" "this" {
  client_id_list = ["sts.amazonaws.com"]
  url            = aws_eks_cluster.this.identity[0].oidc[0].issuer
}

resource "aws_security_group_rule" "jumpbox_to_eks_api" {
  count = var.jumpbox_security_group_id == null ? 0 : 1

  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = aws_security_group.eks.id
  source_security_group_id = var.jumpbox_security_group_id
  description              = "Allow API access from jumpbox to EKS control plane"
}

# Cluster ownership tag. Role/elb tags live on the VPC subnets (do not set them twice).
resource "aws_ec2_tag" "private_cluster" {
  for_each = toset(var.private_subnet_ids)

  resource_id = each.value
  key         = "kubernetes.io/cluster/${aws_eks_cluster.this.name}"
  value       = "shared"
}
