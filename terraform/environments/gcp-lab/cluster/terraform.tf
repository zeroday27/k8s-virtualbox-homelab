terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.10.0"
    }
  }

  # Partial backend config: bucket/prefix come from lab.backend.hcl (gitignored)
  # via `terraform init -backend-config=lab.backend.hcl`.
  backend "gcs" {}
}
