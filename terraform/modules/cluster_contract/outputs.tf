output "intent" {
  description = "Desired VM contract; this output is not proof of provisioned or reachable machines."
  value = {
    schema_version = 1
    cluster_name   = var.spec.name
    profile        = var.spec.profile
    platform       = var.spec.platform
    image          = var.spec.image
    network        = var.spec.network
    ssh_user       = var.spec.security.ssh_user
    nodes          = local.nodes
  }
}

output "resource_budget" {
  description = "Allocated guest resources and disk maximums, not actual consumption."
  value = {
    nodes             = length(local.nodes)
    vcpus             = sum([for node in values(local.nodes) : node.cpus])
    memory_mib        = sum([for node in values(local.nodes) : node.memory_mib])
    disk_capacity_gib = sum([for node in values(local.nodes) : node.root_disk_gib + sum(concat([0], values(node.data_disks)))])
  }
}
