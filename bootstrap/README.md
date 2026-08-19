# Terraform Backend Bootstrap

This directory contains the Terraform configuration to bootstrap the S3 bucket and DynamoDB table required for remote state management.

## Prerequisites

- AWS CLI configured with appropriate credentials
- OpenTofu >= 1.6 (`tofu version`)
- Permissions to create S3 buckets and DynamoDB tables

## Quick Start

1. **Copy the example variables file:**
   ```bash
   cd bootstrap
   cp terraform.tfvars.example terraform.tfvars
   ```

2. **Edit `terraform.tfvars` with your values:**
   - `state_bucket_name`: Must be globally unique across all AWS accounts
   - `aws_region`: Region where you want to store state
   - `dynamodb_table_name`: Name for the DynamoDB locking table

3. **Initialize:**
   ```bash
   tofu init
   ```

4. **Review the plan:**
   ```bash
   tofu plan
   ```

5. **Apply:**
   ```bash
   tofu apply
   ```

6. **Point the stacks at this backend:**
   Uncomment and fill `backend.tf` in `env/dev/network` and `env/dev/workload` (different `key` values), then `tofu init` in each stack.

## What Gets Created

### S3 Bucket
- **Purpose**: Stores Terraform state files
- **Features**:
  - Versioning enabled (for state file recovery)
  - Server-side encryption (AES256)
  - Public access blocked
  - Lifecycle rules:
    - Delete old versions after 90 days
    - Abort incomplete multipart uploads after 7 days

### DynamoDB Table
- **Purpose**: Provides state locking to prevent concurrent modifications
- **Features**:
  - Pay-per-request billing (cost-effective for low usage)
  - Hash key: `LockID` (required by Terraform)

## Security Considerations

- The S3 bucket blocks all public access
- State files are encrypted at rest
- Only users with appropriate IAM permissions can access the bucket
- Consider adding bucket policies to restrict access further if needed

## Cost Estimate

- **S3**: ~$0.023 per GB/month (first 50 TB)
- **DynamoDB**: Pay-per-request, typically < $1/month for small teams
- **Total**: Usually < $5/month for typical usage

## After Bootstrap

Once the backend resources are created:

1. Uncomment and fill `backend.tf` in `env/dev/network` and `env/dev/workload` (different `key` values)
2. Run `tofu init -migrate-state` (or `terraform init -migrate-state`) in each stack
3. Verify: `tofu state list`

## Troubleshooting

### Bucket name already exists
- S3 bucket names must be globally unique
- Try adding your organization name or a unique suffix

### Access denied errors
- Ensure your AWS credentials have permissions for:
  - `s3:CreateBucket`
  - `s3:PutBucketVersioning`
  - `s3:PutBucketEncryption`
  - `s3:PutBucketPublicAccessBlock`
  - `dynamodb:CreateTable`
  - `dynamodb:PutItem`
  - `dynamodb:GetItem`
  - `dynamodb:DeleteItem`

### State migration issues
- If you have existing local state, Terraform will prompt to migrate
- Always backup your local state before migration: `cp terraform.tfstate terraform.tfstate.backup`

