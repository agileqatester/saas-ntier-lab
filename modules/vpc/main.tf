locals {
  common_tags = {
    Environment = var.name_prefix
    Project     = var.name_prefix
    ManagedBy   = "OpenTofu"
  }

  interface_endpoint_subnet_ids = length(var.endpoint_subnet_cidrs) > 0 ? aws_subnet.endpoint[*].id : aws_subnet.private[*].id

  interface_endpoint_sg_id = var.endpoint_security_group_id != "" ? var.endpoint_security_group_id : try(aws_security_group.vpc_endpoints[0].id, "")
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpc"
  })

  lifecycle {
    precondition {
      condition     = length(var.azs) == length(var.public_subnet_cidrs) && length(var.azs) == length(var.private_subnet_cidrs)
      error_message = "azs, public_subnet_cidrs, and private_subnet_cidrs must be the same length."
    }
  }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-igw"
  })
}

resource "aws_subnet" "public" {
  count = length(var.public_subnet_cidrs)

  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = var.azs[count.index]
  map_public_ip_on_launch = true

  tags = merge(local.common_tags, {
    Name                     = "${var.name_prefix}-public-${var.azs[count.index]}"
    "kubernetes.io/role/elb" = "1"
  })
}

resource "aws_subnet" "private" {
  count = length(var.private_subnet_cidrs)

  vpc_id            = aws_vpc.this.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = var.azs[count.index]

  tags = merge(local.common_tags, {
    Name                              = "${var.name_prefix}-private-${var.azs[count.index]}"
    "kubernetes.io/role/internal-elb" = "1"
  })
}

module "nat" {
  count  = var.nat_mode == "none" ? 0 : 1
  source = "../nat"

  name_prefix       = var.name_prefix
  vpc_id            = aws_vpc.this.id
  public_subnet_ids = aws_subnet.public[*].id
  azs               = var.azs
  nat_mode          = var.nat_mode
  nat_instance_ami  = var.nat_instance_ami
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-rt-public"
  })
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count = length(var.public_subnet_cidrs)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count = length(var.private_subnet_cidrs)

  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-rt-private-${var.azs[count.index]}"
  })
}

resource "aws_route" "private_nat_gateway" {
  count = var.nat_mode == "gateway" ? length(var.azs) : 0

  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = module.nat[0].nat_gateway_ids[count.index]
}

resource "aws_route" "private_nat_instance" {
  count = var.nat_mode == "instance" ? length(var.azs) : 0

  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  network_interface_id   = module.nat[0].nat_instance_primary_network_interface_id
}

resource "aws_route_table_association" "private" {
  count = length(var.private_subnet_cidrs)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

resource "aws_subnet" "endpoint" {
  count = length(var.endpoint_subnet_cidrs)

  vpc_id            = aws_vpc.this.id
  cidr_block        = var.endpoint_subnet_cidrs[count.index]
  availability_zone = var.azs[count.index]

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-endpoint-${var.azs[count.index]}"
    Type = "Endpoint"
  })
}

resource "aws_vpc_endpoint" "s3_gateway" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids = concat(
    aws_route_table.private[*].id,
    [aws_route_table.public.id]
  )

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpce-s3"
  })
}

resource "aws_security_group" "vpc_endpoints" {
  count = var.enable_interface_endpoints && var.endpoint_security_group_id == "" ? 1 : 0

  name        = "${var.name_prefix}-vpc-endpoint-sg"
  description = "HTTPS to interface VPC endpoints"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "HTTPS from VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "HTTPS to AWS services"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpc-endpoints-sg"
  })
}

resource "aws_vpc_endpoint" "kinesis_firehose" {
  count = var.enable_interface_endpoints ? 1 : 0

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.kinesis-firehose"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.interface_endpoint_subnet_ids
  security_group_ids  = [local.interface_endpoint_sg_id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpce-kinesis-firehose"
  })
}

resource "aws_vpc_endpoint" "secretsmanager" {
  count = var.enable_interface_endpoints ? 1 : 0

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.interface_endpoint_subnet_ids
  security_group_ids  = [local.interface_endpoint_sg_id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpce-secretsmanager"
  })
}

resource "aws_vpc_endpoint" "eks" {
  count = var.enable_interface_endpoints ? 1 : 0

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.eks"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.interface_endpoint_subnet_ids
  security_group_ids  = [local.interface_endpoint_sg_id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpce-eks"
  })
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  count = var.enable_interface_endpoints ? 1 : 0

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.interface_endpoint_subnet_ids
  security_group_ids  = [local.interface_endpoint_sg_id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpce-ecr-dkr"
  })
}

resource "aws_vpc_endpoint" "ecr_api" {
  count = var.enable_interface_endpoints ? 1 : 0

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.interface_endpoint_subnet_ids
  security_group_ids  = [local.interface_endpoint_sg_id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpce-ecr-api"
  })
}
