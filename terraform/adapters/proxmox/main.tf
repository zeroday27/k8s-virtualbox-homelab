locals {
  spec   = jsondecode(file(var.spec_file))
  bundle = jsondecode(file("${path.module}/../../../versions.lock.json"))
}

module "cluster" {
  source = "../../modules/cluster_contract"
  spec   = local.spec
}

resource "proxmox_virtual_environment_vm" "node" {
  for_each = module.cluster.intent.nodes

  name          = "${local.spec.name}-${each.key}"
  description   = "Terraform managed Kubernetes node: ${each.key}"
  node_name     = var.node_mapping[each.key].node_name
  vm_id         = var.node_mapping[each.key].vm_id
  bios          = "ovmf"
  scsi_hardware = "virtio-scsi-single"
  boot_order    = ["scsi0"]
  tags          = ["terraform", "kubernetes", local.spec.name, each.value.role]

  clone {
    node_name    = var.template.node_name
    vm_id        = var.template.vm_id
    full         = true
    datastore_id = var.node_mapping[each.key].datastore_id
  }
  cpu {
    cores        = each.value.cpus
    type         = local.spec.platform.cpu_model
    architecture = "x86_64"
  }
  memory {
    dedicated = each.value.memory_mib
    floating  = 0
  }
  agent {
    enabled = true
    wait_for_ip {
      ipv4 = true
    }
  }
  efi_disk {
    datastore_id      = var.node_mapping[each.key].datastore_id
    type              = "4m"
    pre_enrolled_keys = true
  }
  disk {
    datastore_id = var.node_mapping[each.key].datastore_id
    interface    = "scsi0"
    size         = each.value.root_disk_gib
    discard      = "on"
  }
  dynamic "disk" {
    for_each = each.value.data_disks
    content {
      datastore_id = var.node_mapping[each.key].datastore_id
      interface    = disk.key
      size         = disk.value
      discard      = "on"
    }
  }
  network_device {
    bridge   = var.node_mapping[each.key].bridge
    vlan_id  = var.node_mapping[each.key].vlan_id
    model    = "virtio"
    firewall = true
  }
  initialization {
    datastore_id = var.node_mapping[each.key].datastore_id
    dns {
      servers = local.spec.network.dns_servers
    }
    ip_config {
      ipv4 {
        address = "${each.value.ip}/${split("/", local.spec.network.node_cidr)[1]}"
        gateway = local.spec.network.gateway
      }
    }
    user_account {
      username = local.spec.security.ssh_user
      keys     = var.ssh_public_keys
    }
  }

  lifecycle {
    prevent_destroy = true
    precondition {
      condition = (
        var.deployment_approved && local.bundle.qualification == "qualified" && local.spec.image.qualified &&
        local.spec.platform.kind == "proxmox" && local.spec.platform.architecture == "x86_64" &&
        var.template.sha256 == local.spec.image.sha256 && var.template.build_id == local.spec.image.build_id &&
        var.template.secure_boot && local.spec.image.secure_boot && each.value.root_disk_gib >= var.template.root_disk_gib
      )
      error_message = "Deployment is gated on a qualified bundle, matching x86_64 template/checksum, Secure Boot and explicit approval."
    }
    precondition {
      condition = (
        local.spec.profile == "production" && local.bundle.addons.qualification == "qualified" &&
        local.spec.components.etcd_mode == "host" && local.spec.dr.enabled && local.spec.dr.independent_backup &&
        local.spec.dr.evidence_ref != null && local.spec.security.secrets_encryption && local.spec.security.audit &&
        local.spec.versions.kubernetes == local.bundle.kubespray.kubernetes &&
        local.spec.versions.kubespray_release == local.bundle.kubespray.release &&
        toset(keys(var.node_mapping)) == toset(keys(module.cluster.intent.nodes))
      )
      error_message = "Production requires the qualified add-on/engine bundle, recovery evidence, security controls and exact node mapping."
    }
    precondition {
      condition     = each.value.hypervisor_host == var.node_mapping[each.key].node_name && var.node_mapping[each.key].vm_id != var.template.vm_id
      error_message = "Placement must match the declared failure domain and must not reuse the template VM ID."
    }
    postcondition {
      condition     = contains(flatten(self.ipv4_addresses), each.value.ip)
      error_message = "The guest agent did not report the expected node address."
    }
  }
}
