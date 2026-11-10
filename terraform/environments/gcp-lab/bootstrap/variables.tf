variable "project_id" {
  description = "Existing Google Cloud project that will host the lab. Keep the real value in terraform.tfvars (gitignored)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a valid Google Cloud project ID (6-30 lowercase letters, digits or hyphens)."
  }
}

variable "region" {
  description = "Region for the state bucket. Keep it in the same region as the lab."
  type        = string
  default     = "asia-east2"
}

variable "state_bucket_name" {
  description = "Globally unique bucket name. Null derives <project_id>-tfstate."
  type        = string
  default     = null

  validation {
    condition     = var.state_bucket_name == null || can(regex("^[a-z0-9][a-z0-9_-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "Bucket names use 3-63 lowercase letters, digits, hyphens or underscores."
  }
}

variable "noncurrent_versions_to_keep" {
  description = "How many older state versions to retain for recovery before lifecycle deletes them."
  type        = number
  default     = 20

  validation {
    condition     = var.noncurrent_versions_to_keep >= 3
    error_message = "Keep at least three noncurrent state versions."
  }
}

variable "enabled_apis" {
  description = "Project APIs the lab needs. Disabling on destroy is turned off so other work is not broken."
  type        = set(string)
  default = [
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iap.googleapis.com",
    "oslogin.googleapis.com",
    "storage.googleapis.com",
  ]
}

variable "labels" {
  description = "Labels applied to every resource the provider creates."
  type        = map(string)
  default = {
    environment = "gcp-lab"
    managed-by  = "terraform"
    purpose     = "learning"
  }
}
