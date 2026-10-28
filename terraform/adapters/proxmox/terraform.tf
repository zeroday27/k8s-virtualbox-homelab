terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.118.0"
    }
  }
  backend "s3" {}
}
