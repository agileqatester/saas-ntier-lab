// NAT module: supports nat_mode = "gateway" (per-AZ NAT gateways) or "instance" (single NAT instance)

resource "aws_eip" "nat" {
  count  = var.nat_mode == "gateway" ? length(var.public_subnet_ids) : 0
  domain = "vpc"
}

resource "aws_nat_gateway" "this" {
  count         = var.nat_mode == "gateway" ? length(var.public_subnet_ids) : 0
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = var.public_subnet_ids[count.index]

  tags = {
    Name = "${var.name_prefix}-nat-${count.index + 1}"
  }
}

// NAT instance resources
resource "aws_eip" "nat_instance" {
  count  = var.nat_mode == "instance" ? 1 : 0
  domain = "vpc"
}

resource "aws_security_group" "nat_instance" {
  count = var.nat_mode == "instance" ? 1 : 0

  name        = "${var.name_prefix}-nat-instance-sg"
  description = "Security group for NAT instance"
  vpc_id      = var.vpc_id

  ingress {
    description = "Traffic from VPC to be NATed (no SSH)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name_prefix}-nat-instance-sg"
  }
}

resource "aws_iam_role" "nat" {
  count = var.nat_mode == "instance" && var.enable_ssm ? 1 : 0

  name = "${var.name_prefix}-nat-ssm"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "nat_ssm" {
  count = var.nat_mode == "instance" && var.enable_ssm ? 1 : 0

  role       = aws_iam_role.nat[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "nat" {
  count = var.nat_mode == "instance" && var.enable_ssm ? 1 : 0

  name = "${var.name_prefix}-nat-ssm"
  role = aws_iam_role.nat[0].name
}

resource "aws_instance" "nat_instance" {
  count         = var.nat_mode == "instance" ? 1 : 0
  ami           = var.nat_instance_ami != "" ? var.nat_instance_ami : data.aws_ami.nat_instance.id
  instance_type = var.nat_instance_type
  subnet_id     = var.public_subnet_ids[0]

  # EIP association makes AWS report this as true; false here forces a replace.
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.nat_instance[0].id]
  source_dest_check           = false
  iam_instance_profile        = var.enable_ssm ? aws_iam_instance_profile.nat[0].name : null

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    delete_on_termination = true
    volume_type           = "gp3"
    volume_size           = 8
  }

  lifecycle {
    ignore_changes = [
      ami,
      credit_specification,
    ]
  }

  user_data = <<-EOF
    #!/bin/bash
    set -eux
    echo 'net.ipv4.ip_forward = 1' > /etc/sysctl.d/99-nat.conf
    sysctl -p /etc/sysctl.d/99-nat.conf
    dnf install -y iptables-nft amazon-ssm-agent
    IFACE=$(ip -o -4 route show default | awk '{print $5}')
    iptables -t nat -A POSTROUTING -o "$IFACE" -j MASQUERADE
    iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
    iptables -A FORWARD -j ACCEPT
    systemctl enable --now amazon-ssm-agent
  EOF

  tags = {
    Name = "${var.name_prefix}-nat-instance"
    Role = "nat"
  }
}

resource "aws_eip_association" "nat_instance" {
  count         = var.nat_mode == "instance" ? 1 : 0
  instance_id   = aws_instance.nat_instance[0].id
  allocation_id = aws_eip.nat_instance[0].id
}

data "aws_ami" "nat_instance" {
  most_recent = true
  owners      = ["137112412989"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023*-kernel-*-arm64"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
