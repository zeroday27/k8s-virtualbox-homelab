run "single_control_plane_lab_budget" {
  command = plan
  assert {
    condition = (
      output.resource_budget.nodes == 3 &&
      output.resource_budget.vcpus == 4 &&
      output.resource_budget.memory_mib == 6144 &&
      output.resource_budget.disk_capacity_gib == 60
    )
    error_message = "The three-node lab resource budget changed unexpectedly."
  }
  assert {
    condition     = output.intent.network.api_vip == output.intent.nodes["cp1"].ip && length([for node in values(output.intent.nodes) : node if node.role == "control_plane"]) == 1
    error_message = "Direct API mode must use the sole control-plane address."
  }
}

run "ha_lab_budget" {
  command = plan
  variables {
    spec_file = "../specs/lab-virtualbox.json"
  }
  assert {
    condition     = output.resource_budget.nodes == 5 && output.resource_budget.memory_mib == 10240 && output.resource_budget.disk_capacity_gib == 88
    error_message = "The minimal lab budget changed unexpectedly."
  }
  assert {
    condition     = output.intent.platform.architecture == "aarch64"
    error_message = "The learning profile must retain ARM64."
  }
}

run "production_example_budget" {
  command = plan
  variables {
    spec_file = "../specs/production-proxmox.example.json"
  }
  assert {
    condition     = output.resource_budget.memory_mib == 40960 && output.resource_budget.disk_capacity_gib == 540
    error_message = "The production example must include worker data disks in its budget."
  }
}

run "reject_direct_api_on_worker" {
  command = plan
  module {
    source = "./modules/cluster_contract"
  }
  variables {
    spec = merge(jsondecode(file("../specs/lab-virtualbox-single.json")), {
      network = merge(jsondecode(file("../specs/lab-virtualbox-single.json")).network, { api_vip = "192.168.56.21" })
    })
  }
  expect_failures = [var.spec]
}

run "reject_single_control_plane_production" {
  command = plan
  module {
    source = "./modules/cluster_contract"
  }
  variables {
    spec = merge(jsondecode(file("../specs/lab-virtualbox-single.json")), { profile = "production" })
  }
  expect_failures = [var.spec]
}

run "reject_api_collision_in_vip_mode" {
  command = plan
  module {
    source = "./modules/cluster_contract"
  }
  variables {
    spec = merge(jsondecode(file("../specs/lab-virtualbox.json")), {
      network = merge(jsondecode(file("../specs/lab-virtualbox.json")).network, { api_vip = "192.168.56.11" })
    })
  }
  expect_failures = [var.spec]
}
