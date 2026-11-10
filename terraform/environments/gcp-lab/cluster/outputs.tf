output "nodes" {
  description = "Provisioned nodes keyed by stable node name. Operational data: keep out of public Git."
  value = {
    for key, vm in google_compute_instance.node : key => {
      name        = vm.name
      role        = var.nodes[key].role
      zone        = vm.zone
      internal_ip = vm.network_interface[0].network_ip
      image       = data.google_compute_image.node.name
    }
  }
}

output "ssh_commands" {
  description = "IAP SSH commands for each node. Key mode uses plain ssh through an IAP ProxyCommand so gcloud never edits instance metadata."
  value = {
    for key, vm in google_compute_instance.node :
    key => (local.use_metadata_ssh_key
      ? "ssh -i ${trimsuffix(var.ssh_public_key_path, ".pub")} -o ProxyCommand='gcloud compute start-iap-tunnel %h 22 --listen-on-stdin --zone ${vm.zone}' ${var.ssh_user}@${vm.name}"
      : "gcloud compute ssh ${vm.name} --zone ${vm.zone} --tunnel-through-iap"
    )
  }
}

output "control_plane_endpoint" {
  description = "Private API endpoint for kubeadm --apiserver-advertise-address."
  value       = one([for key, n in var.nodes : "${n.ip}:6443" if n.role == "control_plane"])
}
