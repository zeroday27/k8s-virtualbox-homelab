variable "spec" {
  description = "Provider-independent intent; validate the complete JSON schema with scripts/specctl.py first."
  type = object({
    api_version = string
    name        = string
    profile     = string
    platform    = object({ kind = string, architecture = string, cpu_model = string })
    image = object({
      key        = string, os = string, release = string, architecture = string,
      source_url = string, sha256 = string, build_id = string, qualified = bool, format = string, secure_boot = bool
    })
    versions = object({ kubespray_release = string, kubernetes = string })
    network = object({
      node_cidr          = string, pod_cidr = string, service_cidr = string,
      api_vip            = string, api_port = number, dns_servers = list(string), ntp_servers = list(string),
      service_pool_start = string, service_pool_end = string, gateway = string
    })
    node_classes = map(object({
      cpus = number, memory_mib = number, root_disk_gib = number, data_disks = map(number)
    }))
    nodes = map(object({
      role            = string, class = string, ip = string, failure_domain = string,
      hypervisor_host = string, interface = string
    }))
    components = object({ api_endpoint = string })
    security   = object({ ssh_user = string })
  })

  validation {
    condition     = var.spec.api_version == "onprem/v1alpha1" && contains(["lab", "production"], var.spec.profile)
    error_message = "Use the supported specification version and lab or production profile."
  }
  validation {
    condition     = var.spec.image.architecture == var.spec.platform.architecture
    error_message = "Image architecture must match the platform architecture."
  }
  validation {
    condition = alltrue([
      for node in values(var.spec.nodes) : contains(keys(var.spec.node_classes), node.class) && contains(["control_plane", "worker"], node.role)
    ])
    error_message = "Every node needs a defined class and supported role."
  }
  validation {
    condition = alltrue([
      for size in values(var.spec.node_classes) : size.cpus >= 1 && size.memory_mib >= 1024 && size.root_disk_gib >= 8
    ])
    error_message = "Node resources are below the contract minimum."
  }
  validation {
    condition = (
      length(distinct([for node in values(var.spec.nodes) : node.ip])) == length(var.spec.nodes) &&
      (var.spec.components.api_endpoint == "node" || !contains([for node in values(var.spec.nodes) : node.ip], var.spec.network.api_vip))
    )
    error_message = "Node addresses must be unique; VIP modes require a separate API address."
  }
  validation {
    condition = alltrue([
      for node in values(var.spec.nodes) : try(cidrhost("${node.ip}/${split("/", var.spec.network.node_cidr)[1]}", 0), "invalid-node") == try(cidrhost(var.spec.network.node_cidr, 0), "invalid-network")
    ])
    error_message = "Node addresses must belong to node_cidr."
  }
  validation {
    condition = contains(var.spec.profile == "lab" ? [1, 3, 5] : [3, 5], length([for node in values(var.spec.nodes) : node if node.role == "control_plane"])) && (
      var.spec.profile != "production" || length(distinct([for node in values(var.spec.nodes) : node.failure_domain if node.role == "control_plane"])) >= 3
    )
    error_message = "Lab allows one/three/five control planes; production requires three/five across independent failure domains."
  }
  validation {
    condition = (
      var.spec.security.ssh_user != "root" &&
      contains(["virtualbox", "proxmox"], var.spec.platform.kind) &&
      contains(["aarch64", "x86_64"], var.spec.platform.architecture)
    )
    error_message = "Use a non-root SSH identity and an explicitly supported platform/architecture."
  }

  validation {
    condition = (
      contains(["node", "kube_vip", "external"], var.spec.components.api_endpoint) &&
      (var.spec.components.api_endpoint != "node" || (
        var.spec.profile == "lab" &&
        length([for node in values(var.spec.nodes) : node if node.role == "control_plane"]) == 1 &&
        contains([for node in values(var.spec.nodes) : node.ip if node.role == "control_plane"], var.spec.network.api_vip)
      ))
    )
    error_message = "Node API mode requires a single-control-plane lab using its control-plane address."
  }
  validation {
    condition     = length([for node in values(var.spec.nodes) : node if node.role == "worker"]) >= 2
    error_message = "At least two workers are required."
  }
}
