output "ansible_inventory" {
  description = "Inventory data only; the listed VMs are not provisioned by this scaffold."
  value       = local.inventory
}

output "resource_budget" {
  description = "Allocated guest resources and virtual disk maximums, not actual host disk usage."
  value = {
    nodes             = length(local.nodes)
    vcpus             = sum([for node in local.nodes : node.cpus])
    memory_mib        = sum([for node in local.nodes : node.memory_mib])
    disk_capacity_gib = sum([for node in local.nodes : node.disk_gib])
  }
}

output "topology" {
  description = "Proposed node configuration, API VIP and application pool."
  value = {
    nodes         = local.nodes
    api_vip       = local.api_vip
    metallb_range = "${cidrhost(var.network_cidr, 200)}-${cidrhost(var.network_cidr, 219)}"
  }
}
