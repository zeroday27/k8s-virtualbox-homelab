terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.10.0"
    }
  }

  # First run uses LOCAL state (terraform.tfstate in this folder, gitignored),
  # because the bucket that will hold remote state does not exist yet.
  # Lesson 3 in ../README.md shows how to move this state into the bucket:
  # uncomment the block below, then run `terraform init -migrate-state`.
  #
  backend "gcs" {}
}
