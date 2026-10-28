locals {
  spec = jsondecode(file(var.spec_file == null ? "${path.module}/../specs/lab-virtualbox-single.json" : var.spec_file))
}

module "cluster" {
  source = "./modules/cluster_contract"
  spec   = local.spec
}
