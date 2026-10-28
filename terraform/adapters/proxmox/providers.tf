provider "proxmox" {
  endpoint = var.endpoint
  insecure = false
  # Authentication is supplied through PROXMOX_VE_API_TOKEN, never through the spec.
}
