provider "google" {
  project        = var.project_id
  region         = var.region
  default_labels = var.labels
  # Credentials come from Application Default Credentials
  # (`gcloud auth application-default login`). No key files.
}
