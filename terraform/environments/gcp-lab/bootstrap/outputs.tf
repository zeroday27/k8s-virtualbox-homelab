output "state_bucket" {
  description = "Name of the remote state bucket."
  value       = google_storage_bucket.state.name
}

output "cluster_backend_config" {
  description = "Paste into ../cluster/lab.backend.hcl (gitignored)."
  value       = <<-EOT
    bucket = "${google_storage_bucket.state.name}"
    prefix = "gcp-lab/cluster"
  EOT
}
