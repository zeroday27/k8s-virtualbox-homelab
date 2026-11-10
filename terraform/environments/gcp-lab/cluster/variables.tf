variable "project_id" {
  description = "Existing Google Cloud project for the lab. Keep the real value in terraform.tfvars (gitignored)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a valid Google Cloud project ID."
  }
}

variable "region" {
  description = "Region for the network, NAT and subnet."
  type        = string
  default     = "asia-east2"
}

variable "zone" {
  description = "Zone for all three VMs. A single zone is acceptable for a lab, not for production."
  type        = string
  default     = "asia-east2-a"

  validation {
    condition     = startswith(var.zone, "${var.region}-")
    error_message = "The zone must belong to the selected region."
  }
}

variable "name_prefix" {
  description = "Prefix for every resource name; also the VM hostname prefix."
  type        = string
  default     = "k8s-lab"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.name_prefix))
    error_message = "Use 2-21 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "subnet_cidr" {
  description = "Node subnet. Must not overlap pod_cidr or the Kubernetes service CIDR (10.96.0.0/12)."
  type        = string
  default     = "10.10.0.0/24"
}

variable "pod_cidr" {
  description = "Calico pod CIDR used later by kubeadm; allowed by the internal firewall rule."
  type        = string
  default     = "10.244.0.0/16"
}

variable "nodes" {
  description = "Stable node keys, as in the repository specs. Exactly one control plane and at least two workers."
  type = map(object({
    role         = string
    machine_type = string
    disk_gib     = number
    ip           = string
  }))
  default = {
    cp1     = { role = "control_plane", machine_type = "e2-medium", disk_gib = 30, ip = "10.10.0.11" }
    worker1 = { role = "worker", machine_type = "e2-medium", disk_gib = 30, ip = "10.10.0.21" }
    worker2 = { role = "worker", machine_type = "e2-medium", disk_gib = 30, ip = "10.10.0.22" }
  }

  validation {
    condition     = length([for n in values(var.nodes) : n if n.role == "control_plane"]) == 1
    error_message = "This lab expects exactly one control-plane node."
  }
  validation {
    condition     = length([for n in values(var.nodes) : n if n.role == "worker"]) >= 2
    error_message = "At least two workers are required."
  }
  validation {
    condition     = alltrue([for n in values(var.nodes) : contains(["control_plane", "worker"], n.role) && n.disk_gib >= 20])
    error_message = "Roles must be control_plane or worker, and disks at least 20 GiB."
  }
  validation {
    condition     = length(distinct([for n in values(var.nodes) : n.ip])) == length(var.nodes)
    error_message = "Node IPs must be unique."
  }
  validation {
    condition = alltrue([
      for n in values(var.nodes) :
      can(cidrhost("${n.ip}/32", 0)) && cidrhost("${n.ip}/${split("/", var.subnet_cidr)[1]}", 0) == cidrhost(var.subnet_cidr, 0)
    ])
    error_message = "Every node IP must be inside subnet_cidr."
  }
}

variable "image_family" {
  description = "Public image family. Verify it exists first: gcloud compute images describe-from-family <family> --project <image_project>."
  type        = string
  default     = "ubuntu-2604-lts-amd64"
}

variable "image_project" {
  description = "Project that publishes image_family."
  type        = string
  default     = "ubuntu-os-cloud"
}

variable "disk_type" {
  description = "Boot disk type."
  type        = string
  default     = "pd-balanced"
}

variable "ssh_public_key_path" {
  description = "Path to an existing OpenSSH PUBLIC key (.pub). Set: OS Login is off and ssh_user logs in with this key. Null: OS Login with your Google identity."
  type        = string
  default     = null

  validation {
    condition = var.ssh_public_key_path == null || (
      endswith(var.ssh_public_key_path, ".pub") &&
      can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/=]+", file(pathexpand(var.ssh_public_key_path))))
    )
    error_message = "Point to a readable OpenSSH public key ending in .pub; never a private key."
  }
}

variable "ssh_user" {
  description = "Linux user created for the metadata SSH key. Matches the local lab Ansible inventory."
  type        = string
  default     = "ubuntu"

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_-]{0,31}$", var.ssh_user)) && var.ssh_user != "root"
    error_message = "Use a valid non-root Linux user name."
  }
}

variable "use_spot" {
  description = "Spot VMs are much cheaper but Google can stop them at any time. Fine for practice, not for anything you care about."
  type        = bool
  default     = false
}

variable "enable_cloud_nat" {
  description = "Outbound internet for private nodes (apt, container images). Nodes have no public IPs."
  type        = bool
  default     = true
}

variable "deletion_protection" {
  description = "Blocks VM deletion until set to false. Off by default so the lab is easy to tear down."
  type        = bool
  default     = false
}

variable "labels" {
  description = "Labels applied to every resource the provider creates."
  type        = map(string)
  default = {
    environment = "gcp-lab"
    managed-by  = "terraform"
    purpose     = "learning"
  }
}
