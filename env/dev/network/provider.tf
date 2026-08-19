provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Environment = "dev"
      Project     = var.name_prefix
      ManagedBy   = "OpenTofu"
      Stack       = "network"
    }
  }
}
