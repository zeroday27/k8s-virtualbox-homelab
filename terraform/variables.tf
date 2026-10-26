variable "network_cidr" {
  description = "Proposed host-only IPv4 /24, subject to local route conflict checks."
  type        = string
  default     = "192.168.56.0/24"

  validation {
    condition     = can(cidrnetmask(var.network_cidr)) && endswith(var.network_cidr, "/24")
    error_message = "Use a valid IPv4 /24 for the fixed lab address layout."
  }
}

variable "ssh_user" {
  description = "Non-root Ubuntu account created during image bootstrap."
  type        = string
  default     = "ubuntu"
}
