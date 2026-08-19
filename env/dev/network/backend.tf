# Remote state — uncomment after bootstrap/. Public repo uses S3; this laptop may stay local until then.
#
# terraform {
#   backend "s3" {
#     bucket         = "your-org-ntier-app-terraform-state"
#     key            = "ntier-app/dev/network/terraform.tfstate"
#     region         = "us-east-1"
#     dynamodb_table = "terraform-state-locks"
#     encrypt        = true
#   }
# }
