# Ultra-cheap custom NAT instance with user data script

resource "aws_instance" "custom_nat" {
  count                  = var.nat_mode == "custom" ? 1 : 0
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = "t4g.nano" # Cheapest ARM instance ~$3.80/month
  subnet_id              = var.public_subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.custom_nat[0].id]
  source_dest_check      = false

  user_data = base64encode(<<-EOF
    #!/bin/bash
    # Enable IP forwarding
    echo 'net.ipv4.ip_forward = 1' >> /etc/sysctl.conf
    sysctl -p
    
    # Configure iptables for NAT
    iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
    iptables -A FORWARD -i eth0 -o eth0 -m state --state RELATED,ESTABLISHED -j ACCEPT
    iptables -A FORWARD -i eth0 -o eth0 -j ACCEPT
    
    # Save iptables rules
    iptables-save > /etc/iptables.rules
    
    # Restore iptables on boot
    echo 'iptables-restore < /etc/iptables.rules' >> /etc/rc.local
    chmod +x /etc/rc.local
    
    # Install CloudWatch agent for monitoring (optional)
    dnf install -y amazon-cloudwatch-agent
  EOF
  )

  tags = {
    Name = "${var.name_prefix}-custom-nat"
    Type = "NAT"
  }
}

resource "aws_security_group" "custom_nat" {
  count = var.nat_mode == "custom" ? 1 : 0

  name_prefix = "${var.name_prefix}-custom-nat-"
  vpc_id      = var.vpc_id

  # Allow all traffic from private subnets
  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["10.0.0.0/8"] # Adjust to your VPC CIDR
  }

  # Allow all outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name_prefix}-custom-nat-sg"
  }
}

data "aws_ami" "amazon_linux" {
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
}

# EIP for custom NAT
resource "aws_eip" "custom_nat" {
  count    = var.nat_mode == "custom" ? 1 : 0
  instance = aws_instance.custom_nat[0].id
  domain   = "vpc"

  tags = {
    Name = "${var.name_prefix}-custom-nat-eip"
  }
}