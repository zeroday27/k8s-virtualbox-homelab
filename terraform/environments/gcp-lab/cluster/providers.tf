provider "google" {
  project        = var.project_id
  region         = var.region
  zone           = var.zone
  default_labels = var.labels
  # Credentials come from Application Default Credentials. No key files.
}
