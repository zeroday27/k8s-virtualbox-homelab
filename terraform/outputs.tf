output "intent" {
  description = "Planning output only. No VM provider is called by this root module."
  value       = module.cluster.intent
}

output "resource_budget" {
  description = "Guest allocation budget calculated from the selected specification."
  value       = module.cluster.resource_budget
}

output "topology" {
  description = "Proposed topology, API endpoint address (legacy api_vip field) and optional MetalLB pool."
  value = {
    nodes         = module.cluster.intent.nodes
    api_vip       = local.spec.network.api_vip
    metallb_range = "${local.spec.network.service_pool_start}-${local.spec.network.service_pool_end}"
  }
}
