output "state_bucket_name" {
  description = "Name of the S3 bucket for Terraform state"
  value       = aws_s3_bucket.terraform_state.id
}

output "state_bucket_arn" {
  description = "ARN of the S3 bucket for Terraform state"
  value       = aws_s3_bucket.terraform_state.arn
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB table for state locking"
  value       = aws_dynamodb_table.terraform_locks.name
}

output "dynamodb_table_arn" {
  description = "ARN of the DynamoDB table for state locking"
  value       = aws_dynamodb_table.terraform_locks.arn
}

output "kms_key_id" {
  description = "KMS key ID used for S3 bucket encryption"
  value       = aws_kms_key.terraform_state.id
}

output "kms_key_arn" {
  description = "KMS key ARN used for S3 bucket encryption"
  value       = aws_kms_key.terraform_state.arn
}

output "backend_config" {
  description = "Terraform backend configuration block"
  value       = <<-EOT
    terraform {
      backend "s3" {
        bucket         = "${aws_s3_bucket.terraform_state.id}"
        key            = "ntier-app/terraform.tfstate"
        region         = "${var.aws_region}"
        dynamodb_table = "${aws_dynamodb_table.terraform_locks.name}"
        encrypt        = true
        kms_key_id     = "${aws_kms_key.terraform_state.arn}"
      }
    }
  EOT
}

