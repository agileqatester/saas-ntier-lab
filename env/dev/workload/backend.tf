# Remote state — uncomment after bootstrap/. Use a different key than network.
#
# terraform {
#   backend "s3" {
#     bucket         = "your-org-ntier-app-terraform-state"
#     key            = "ntier-app/dev/workload/terraform.tfstate"
#     region         = "us-east-1"
#     dynamodb_table = "terraform-state-locks"
#     encrypt        = true
#   }
# }
