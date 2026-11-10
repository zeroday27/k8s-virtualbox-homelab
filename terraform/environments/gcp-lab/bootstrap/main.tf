locals {
  state_bucket_name = coalesce(var.state_bucket_name, "${var.project_id}-tfstate")
}

resource "google_project_service" "lab" {
  for_each = var.enabled_apis

  service            = each.value
  disable_on_destroy = false
}

# Remote state bucket for the cluster root (and, optionally, this root).
# Versioning gives point-in-time recovery of state; the GCS backend uses
# native object locking, so no separate lock table is needed.
resource "google_storage_bucket" "state" {
  name                        = local.state_bucket_name
  location                    = upper(var.region)
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = var.noncurrent_versions_to_keep
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.lab]

  lifecycle {
    prevent_destroy = true
  }
}
