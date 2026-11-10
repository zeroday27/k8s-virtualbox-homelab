locals {
  use_metadata_ssh_key = var.ssh_public_key_path != null

  # OS Login ignores metadata keys, so the two modes are exclusive.
  # block-project-ssh-keys stays on: only this instance-level key is accepted.
  ssh_metadata = local.use_metadata_ssh_key ? {
    enable-oslogin         = "FALSE"
    block-project-ssh-keys = "TRUE"
    ssh-keys               = "${var.ssh_user}:${trimspace(file(pathexpand(var.ssh_public_key_path)))}"
    } : {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
  }
}

data "google_compute_image" "node" {
  family  = var.image_family
  project = var.image_project
}

# Dedicated identity instead of the broad default Compute Engine service account.
resource "google_service_account" "node" {
  account_id   = "${var.name_prefix}-node"
  display_name = "Kubernetes lab node (${var.name_prefix})"
}

resource "google_project_iam_member" "node" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.node.email}"
}

resource "google_compute_instance" "node" {
  for_each = var.nodes

  name                      = "${var.name_prefix}-${each.key}"
  zone                      = var.zone
  machine_type              = each.value.machine_type
  can_ip_forward            = true
  deletion_protection       = var.deletion_protection
  allow_stopping_for_update = true
  tags                      = [local.node_tag, "${var.name_prefix}-${replace(each.value.role, "_", "-")}"]

  boot_disk {
    auto_delete = true

    initialize_params {
      image = data.google_compute_image.node.self_link
      size  = each.value.disk_gib
      type  = var.disk_type
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.nodes.id
    network_ip = each.value.ip
    # No access_config block: no public IP. Reach nodes through IAP.
  }

  service_account {
    email  = google_service_account.node.email
    scopes = ["cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  scheduling {
    provisioning_model          = var.use_spot ? "SPOT" : "STANDARD"
    preemptible                 = var.use_spot
    automatic_restart           = !var.use_spot
    on_host_maintenance         = var.use_spot ? "TERMINATE" : "MIGRATE"
    instance_termination_action = var.use_spot ? "STOP" : null
  }

  metadata = local.ssh_metadata

  labels = {
    role = replace(each.value.role, "_", "-")
    node = each.key
  }

  lifecycle {
    # New image releases in the family must not silently rebuild nodes.
    ignore_changes = [boot_disk[0].initialize_params[0].image]
  }
}
