# Offline tests: the mocked provider never calls Google Cloud.
# Run: terraform init -backend=false && terraform test
mock_provider "google" {}

variables {
  project_id = "example-lab-project"
}

run "default_topology" {
  command = plan

  assert {
    condition     = length(google_compute_instance.node) == 3
    error_message = "Expected one control plane and two workers."
  }
  assert {
    condition     = alltrue([for vm in values(google_compute_instance.node) : length(vm.network_interface[0].access_config) == 0])
    error_message = "Nodes must not have public IPs."
  }
  assert {
    condition     = google_compute_instance.node["cp1"].network_interface[0].network_ip == "10.10.0.11"
    error_message = "Control-plane address changed unexpectedly."
  }
  assert {
    condition     = google_compute_firewall.iap.source_ranges == toset(["35.235.240.0/20"])
    error_message = "Admin access must stay limited to the IAP range."
  }
  assert {
    condition     = length(google_compute_router_nat.this) == 1
    error_message = "Cloud NAT should be on by default."
  }
}

run "spot_scheduling" {
  command = plan

  variables {
    use_spot = true
  }

  assert {
    condition     = alltrue([for vm in values(google_compute_instance.node) : vm.scheduling[0].provisioning_model == "SPOT"])
    error_message = "use_spot must switch every node to Spot."
  }
}

run "reject_two_control_planes" {
  command = plan

  variables {
    nodes = {
      cp1     = { role = "control_plane", machine_type = "e2-medium", disk_gib = 30, ip = "10.10.0.11" }
      cp2     = { role = "control_plane", machine_type = "e2-medium", disk_gib = 30, ip = "10.10.0.12" }
      worker1 = { role = "worker", machine_type = "e2-medium", disk_gib = 30, ip = "10.10.0.21" }
      worker2 = { role = "worker", machine_type = "e2-medium", disk_gib = 30, ip = "10.10.0.22" }
    }
  }

  expect_failures = [var.nodes]
}

run "reject_ip_outside_subnet" {
  command = plan

  variables {
    nodes = {
      cp1     = { role = "control_plane", machine_type = "e2-medium", disk_gib = 30, ip = "10.20.0.11" }
      worker1 = { role = "worker", machine_type = "e2-medium", disk_gib = 30, ip = "10.10.0.21" }
      worker2 = { role = "worker", machine_type = "e2-medium", disk_gib = 30, ip = "10.10.0.22" }
    }
  }

  expect_failures = [var.nodes]
}

run "metadata_ssh_key_mode" {
  command = plan

  variables {
    ssh_public_key_path = "tests/fixtures/example.pub"
  }

  assert {
    condition = alltrue([
      for vm in values(google_compute_instance.node) :
      vm.metadata["enable-oslogin"] == "FALSE" && startswith(vm.metadata["ssh-keys"], "ubuntu:ssh-ed25519 ")
    ])
    error_message = "Key mode must disable OS Login and install the key for ubuntu."
  }
}

run "default_uses_os_login" {
  command = plan

  variables {
    ssh_public_key_path = null
  }

  assert {
    condition     = alltrue([for vm in values(google_compute_instance.node) : vm.metadata["enable-oslogin"] == "TRUE" && !contains(keys(vm.metadata), "ssh-keys")])
    error_message = "Without a key path, nodes must use OS Login only."
  }
}

run "reject_private_key_path" {
  command = plan

  variables {
    ssh_public_key_path = "tests/fixtures/example"
  }

  expect_failures = [var.ssh_public_key_path]
}
