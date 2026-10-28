locals {
  nodes = {
    for name, node in var.spec.nodes : name => merge(node, var.spec.node_classes[node.class], {
      image_key    = var.spec.image.key
      architecture = var.spec.platform.architecture
      disk_gib     = var.spec.node_classes[node.class].root_disk_gib
    })
  }
}
