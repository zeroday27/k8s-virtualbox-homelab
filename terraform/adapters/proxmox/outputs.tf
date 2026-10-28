output "provisioned_nodes" {
  description = "Apply/refresh observations for inventory compilation. The guest agent must report each expected IP."
  value = {
    for name, vm in proxmox_virtual_environment_vm.node : name => {
      id              = tostring(vm.id)
      ip              = module.cluster.intent.nodes[name].ip
      observed_ips    = flatten(vm.ipv4_addresses)
      hypervisor_host = vm.node_name
      image_build_id  = var.template.build_id
    }
  }
}
