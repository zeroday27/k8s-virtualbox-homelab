locals {
  node_specs = {
    cp1     = { role = "control_plane", host = 11, cpus = 2, memory_mib = 2048, disk_gib = 16 }
    cp2     = { role = "control_plane", host = 12, cpus = 2, memory_mib = 2048, disk_gib = 16 }
    cp3     = { role = "control_plane", host = 13, cpus = 2, memory_mib = 2048, disk_gib = 16 }
    worker1 = { role = "worker", host = 21, cpus = 1, memory_mib = 2048, disk_gib = 20 }
    worker2 = { role = "worker", host = 22, cpus = 1, memory_mib = 2048, disk_gib = 20 }
  }
  nodes = {
    for name, spec in local.node_specs : name => merge(spec, {
      ip = cidrhost(var.network_cidr, spec.host)
    })
  }
  api_vip = cidrhost(var.network_cidr, 10)
  inventory = {
    all = {
      vars = {
        ansible_user                = var.ssh_user
        ansible_python_interpreter  = "/usr/bin/python3"
        kube_api_endpoint           = "${local.api_vip}:6443"
        lab_expected_architecture   = "aarch64"
        lab_expected_ubuntu_version = "26.04"
      }
      children = {
        control_plane = {
          hosts = { for name, node in local.nodes : name => { ansible_host = node.ip } if node.role == "control_plane" }
        }
        workers = {
          hosts = { for name, node in local.nodes : name => { ansible_host = node.ip } if node.role == "worker" }
        }
      }
    }
  }
}
