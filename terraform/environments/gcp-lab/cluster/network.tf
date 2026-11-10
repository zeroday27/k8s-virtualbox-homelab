locals {
  # Google's published source range for Identity-Aware Proxy TCP forwarding.
  iap_source_range = "35.235.240.0/20"
  node_tag         = "${var.name_prefix}-node"
}

resource "google_compute_network" "this" {
  name                    = "${var.name_prefix}-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  mtu                     = 1460
}

resource "google_compute_subnetwork" "nodes" {
  name                     = "${var.name_prefix}-nodes"
  region                   = var.region
  network                  = google_compute_network.this.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
}

# Node-to-node and pod traffic inside the cluster. Calico's default manifest
# uses IP-in-IP (protocol "ipip"); VXLAN uses UDP 4789, covered by "udp".
resource "google_compute_firewall" "internal" {
  name          = "${var.name_prefix}-allow-internal"
  network       = google_compute_network.this.id
  direction     = "INGRESS"
  source_ranges = [var.subnet_cidr, var.pod_cidr]
  target_tags   = [local.node_tag]

  allow {
    protocol = "tcp"
  }
  allow {
    protocol = "udp"
  }
  allow {
    protocol = "icmp"
  }
  allow {
    protocol = "ipip"
  }
}

# SSH and the Kubernetes API only through IAP. Nothing is open to the internet.
resource "google_compute_firewall" "iap" {
  name          = "${var.name_prefix}-allow-iap"
  network       = google_compute_network.this.id
  direction     = "INGRESS"
  source_ranges = [local.iap_source_range]
  target_tags   = [local.node_tag]

  allow {
    protocol = "tcp"
    ports    = ["22", "6443"]
  }
}

resource "google_compute_router" "this" {
  count = var.enable_cloud_nat ? 1 : 0

  name    = "${var.name_prefix}-router"
  region  = var.region
  network = google_compute_network.this.id
}

resource "google_compute_router_nat" "this" {
  count = var.enable_cloud_nat ? 1 : 0

  name                               = "${var.name_prefix}-nat"
  router                             = google_compute_router.this[0].name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.nodes.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
