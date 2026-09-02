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

6. **Point Terragrunt at this backend:**
   Copy `live/backend.hcl.example` to `live/backend.hcl` (gitignored) and fill `bucket`, `dynamodb_table`, and `kms_key_id` from the outputs below. Terragrunt generates `backend.tf` per unit and will **not** create or mutate this bucket.

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

1. Copy `live/backend.hcl.example` to `live/backend.hcl` and fill from `tofu output`
2. Run `terragrunt init` in `live/dev/network` and `live/dev/workload` (add `-migrate-state` if you already had local state)
3. Verify: `terragrunt state list`

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

