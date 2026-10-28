variable "deployment_approved" {
  description = "Explicit release gate after image, adapter, OS and recovery qualification. Not proof by itself."
  type        = bool
  default     = false
}

variable "endpoint" {
  description = "Private Proxmox API endpoint with a certificate trusted by the runner."
  type        = string
  validation {
    condition     = startswith(var.endpoint, "https://")
    error_message = "A trusted HTTPS Proxmox endpoint is required."
  }
}

variable "node_mapping" {
  description = "Site-specific placement and storage, keyed by the stable node names in the specification."
  type = map(object({
    node_name = string, vm_id = number, datastore_id = string, bridge = string,
    vlan_id   = optional(number)
  }))
  validation {
    condition     = length(distinct([for mapping in values(var.node_mapping) : mapping.vm_id])) == length(var.node_mapping)
    error_message = "VM IDs must be unique."
  }
}

variable "spec_file" {
  description = "Absolute path to the private, schema-validated production cluster specification."
  type        = string
}

variable "ssh_public_keys" {
  description = "Existing administrator public keys; private keys and passwords never enter Terraform."
  type        = list(string)
  validation {
    condition     = length(var.ssh_public_keys) > 0 && alltrue([for key in var.ssh_public_keys : can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-)[^\\n]* ", key))])
    error_message = "Provide at least one OpenSSH public key."
  }
}

variable "template" {
  description = "Qualified generalized UEFI template with cloud-init, Python, sudo and QEMU guest agent already installed."
  type = object({
    node_name     = string, vm_id = number, build_id = string, sha256 = string,
    root_disk_gib = number, secure_boot = bool
  })
}
