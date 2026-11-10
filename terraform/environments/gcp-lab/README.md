# GCP VM lab: 1 control plane + 2 workers (no GKE)

A separate learning environment. Terraform creates plain Compute Engine VMs;
you install Kubernetes yourself with kubeadm. It does not use the on-premises
`cluster_contract` module, the Proxmox adapter or any production gate.

```
                        Google Cloud project (your own)
 ┌───────────────────────────────────────────────────────────────────────┐
 │  GCS bucket <project>-tfstate   (versioned, private, holds state)     │
 │                                                                       │
 │  VPC k8s-lab-vpc ── subnet 10.10.0.0/24 (asia-east2)                  │
 │     ├─ k8s-lab-cp1      10.10.0.11  e2-medium  control plane          │
 │     ├─ k8s-lab-worker1  10.10.0.21  e2-medium  worker                 │
 │     └─ k8s-lab-worker2  10.10.0.22  e2-medium  worker                 │
 │  No public IPs. Inbound: IAP only (22, 6443). Outbound: Cloud NAT.    │
 └───────────────────────────────────────────────────────────────────────┘
        ▲ gcloud compute ssh --tunnel-through-iap (your laptop)
```

## Layout

| Path | State | Creates |
| --- | --- | --- |
| `bootstrap/` | Local first, optional migration to GCS | Project APIs, state bucket |
| `cluster/` | GCS bucket, prefix `gcp-lab/cluster` | VPC, subnet, firewall, NAT, service account, 3 VMs |
| `cluster/tests/` | None (mocked provider) | Offline `terraform test` checks |

Private files you create (all gitignored): `terraform.tfvars`, `*.backend.hcl`,
`terraform.tfstate*`, `.terraform/`. Never commit them; this repository is public.

## Lesson 0: concepts in five minutes

- **Provider**: plugin that talks to an API (`hashicorp/google`, pinned in `terraform.tf`).
- **Resource / data source**: something Terraform manages / something it only reads (the Ubuntu image).
- **State**: Terraform's record of what it created. Lose it and Terraform forgets your VMs.
- **Backend**: where state lives. Remote (GCS) gives locking, versioning and sharing.
- **Bootstrap problem**: the bucket for remote state must exist before any root can use it,
  so a tiny `bootstrap/` root creates it with local state first.
- **Workflow**: `init` (download provider, connect backend) → `plan` (diff) → `apply` → `destroy`.

## Lesson 1: prerequisites (once)

1. A Google Cloud project with billing enabled. Use a personal lab project, not a work one.
   Create a budget alert in the console (Billing → Budgets & alerts) before applying anything.
2. Your user needs, on that project: Owner, or at least Compute Admin, Storage Admin,
   Service Usage Admin, Service Account Admin, Project IAM Admin, IAP-secured Tunnel User
   and Compute OS Admin Login.
3. Authenticate (opens a browser; no key files are created):

```sh
gcloud auth login
gcloud config set project <PROJECT_ID>
gcloud auth application-default login
gcloud auth application-default set-quota-project <PROJECT_ID>
gcloud config list            # confirm the project before every session
```

4. Confirm the image family exists (the default is Ubuntu 26.04 x86_64):

```sh
gcloud compute images describe-from-family ubuntu-2604-lts-amd64 --project ubuntu-os-cloud --format='value(name,status)'
```

If it fails, list options with
`gcloud compute images list --project ubuntu-os-cloud --filter='family~lts' --format='value(family)' | sort -u`
and set `image_family` in `cluster/terraform.tfvars`.

## Lesson 2: bootstrap the state bucket

```sh
cd terraform/environments/gcp-lab/bootstrap
cp terraform.tfvars.example terraform.tfvars      # edit project_id
terraform init
terraform fmt -check && terraform validate
terraform plan -out=bootstrap.tfplan              # read it: 5 APIs + 1 bucket
terraform apply bootstrap.tfplan
terraform output -raw cluster_backend_config      # you need this in Lesson 4
```

What to notice in the plan: `versioning`, `public_access_prevention = "enforced"`,
`uniform_bucket_level_access = true`. The bucket has `prevent_destroy`, so
`terraform destroy` here refuses on purpose. Verify:

```sh
gcloud storage buckets describe gs://<BUCKET> --format='yaml(versioning,iamConfiguration)'
```

## Lesson 3 (optional practice): move bootstrap state into the bucket

Local `terraform.tfstate` is a single point of loss. Migrating teaches `-migrate-state`.

```sh
cp backend.hcl.example bootstrap.backend.hcl      # set the real bucket
# uncomment `backend "gcs" {}` in terraform.tf
terraform init -migrate-state -backend-config=bootstrap.backend.hcl   # answer yes
terraform plan                                     # must say: No changes
gcloud storage ls gs://<BUCKET>/gcp-lab/bootstrap/
```

Keep the old local `terraform.tfstate` until the plan shows no changes, then delete it yourself.

## Lesson 4: provision the cluster VMs

```sh
cd ../cluster
cp terraform.tfvars.example terraform.tfvars      # edit project_id
cp backend.hcl.example lab.backend.hcl            # paste the bootstrap output
terraform init -backend-config=lab.backend.hcl
terraform validate
terraform test                                     # offline, mocked provider
terraform plan -out=cluster.tfplan
```

Read the plan before applying. Expect about 12 resources: network, subnet,
2 firewall rules, router, NAT, service account, 2 IAM bindings, 3 instances.
Check that no instance has `access_config` (no public IP).

```sh
terraform apply cluster.tfplan
terraform output
gcloud storage ls gs://<BUCKET>/gcp-lab/cluster/   # default.tfstate now lives here
```

## Lesson 5: verify the VMs

```sh
gcloud compute instances list --filter='labels.environment=gcp-lab'
terraform output -json ssh_commands
gcloud compute ssh k8s-lab-cp1 --zone asia-east2-a --tunnel-through-iap
# on the node:
hostname -I; nproc; free -m; curl -sI https://pkgs.k8s.io | head -1   # NAT works
ping -c2 10.10.0.21                                                   # internal firewall works
```

The first SSH may take a minute while OS Login provisions your user.

**Key mode (reuse an existing lab key as `ubuntu`).** Set `ssh_public_key_path` (a `.pub`
file) in `cluster/terraform.tfvars`. Terraform turns OS Login off and writes
`ubuntu:<public key>` into each VM's metadata. Use plain `ssh` through an IAP
ProxyCommand (shown in `terraform output ssh_commands`); avoid `gcloud compute ssh`
here, because it may add its own key to instance metadata and cause drift.

```sh
ssh -i ~/.ssh/<lab-key> \
  -o ProxyCommand='gcloud compute start-iap-tunnel %h 22 --listen-on-stdin --zone asia-east2-a' \
  ubuntu@k8s-lab-cp1
```

Access then depends on holding the private key, not on Google IAM. Switching
modes is an in-place metadata update, not a VM rebuild.

## Lesson 6: install Kubernetes with kubeadm (manual, by hand first)

These steps are a learning path, not a qualified runbook. Versions follow
`ansible/vars/k8s-base.bom.json` (Kubernetes 1.37.2, Calico 3.33.0, amd64).
Check upstream docs if a command fails.

**All three nodes:**

```sh
sudo modprobe overlay && sudo modprobe br_netfilter
printf 'overlay\nbr_netfilter\n' | sudo tee /etc/modules-load.d/k8s.conf
printf 'net.bridge.bridge-nf-call-iptables=1\nnet.bridge.bridge-nf-call-ip6tables=1\nnet.ipv4.ip_forward=1\n' | sudo tee /etc/sysctl.d/99-k8s.conf
sudo sysctl --system

sudo apt-get update && sudo apt-get install -y containerd apt-transport-https ca-certificates curl gpg
sudo mkdir -p /etc/containerd && containerd config default | sudo tee /etc/containerd/config.toml >/dev/null
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
grep SystemdCgroup /etc/containerd/config.toml     # must show true
sudo systemctl restart containerd

sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.37/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.37/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update && sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
```

**Control plane only (`k8s-lab-cp1`):**

```sh
sudo kubeadm init --kubernetes-version v1.37.2 \
  --apiserver-advertise-address 10.10.0.11 \
  --pod-network-cidr 10.244.0.0/16
mkdir -p ~/.kube && sudo cp /etc/kubernetes/admin.conf ~/.kube/config && sudo chown "$(id -u):$(id -g)" ~/.kube/config

curl -fsSLO https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/calico.yaml
echo "2de8f47595fb9c41b3f47d7b767a1f8e72ecf84057af834738ff12689a234da5  calico.yaml" | sha256sum -c
# Edit calico.yaml: uncomment CALICO_IPV4POOL_CIDR and set value "10.244.0.0/16"
kubectl apply -f calico.yaml
kubeadm token create --print-join-command          # copy the output
```

**Each worker:** run the printed `sudo kubeadm join ...` command.

**Check (on cp1):**

```sh
kubectl get nodes -o wide                          # 3 nodes Ready after a few minutes
kubectl get pods -A
kubectl create deployment web --image=nginx --replicas=3 && kubectl get pods -o wide
```

`admin.conf` is a cluster-admin credential. Keep it on the node; do not copy it into the repository.

## Lesson 7: practice exercises (Terraform skills)

Run `terraform plan` after each change and explain the diff before applying.

1. **Update in place vs replace**: change `machine_type` of `worker2` to `e2-standard-2`.
   The plan shows an in-place update (VM stops and starts, `allow_stopping_for_update`).
   Then change `disk_gib` and look for `# forces replacement` in the plan. Revert both.
2. **Scale out**: add `worker3 = { role = "worker", ..., ip = "10.10.0.23" }`. Only one
   resource is added because `for_each` keys are stable. Join it with kubeadm.
3. **Validation**: give `worker3` the IP `10.20.0.23`; `plan` fails on the variable rule.
4. **Drift**: add a label to `k8s-lab-worker1` in the console, then `terraform plan`.
   Terraform proposes to remove it. Decide: apply (reconcile) or adopt it in code.
5. **State inspection**: `terraform state list`, `terraform state show 'google_compute_instance.node["cp1"]'`.
6. **Forced rebuild**: `terraform apply -replace='google_compute_instance.node["worker2"]'`,
   then drain/delete/rejoin it in Kubernetes. This is how you recover a broken node.
7. **Refactor safely**: rename the resource `node` to `vm` and add a `moved` block so the
   plan shows zero changes.
8. **Import**: create a firewall rule by hand with `gcloud`, write a matching resource
   plus an `import` block, and plan until it shows only the import.
9. **Spot**: set `use_spot = true`. Read whether the plan updates or replaces the VMs, and why.
10. **State recovery**: list versions with `gcloud storage ls -a gs://<BUCKET>/gcp-lab/cluster/`
    and read how you would restore an older generation (do not overwrite live state casually).

## Lesson 8: control cost and tear down

VMs, boot disks, NAT and logs cost money while they exist. Check prices in the
Google Cloud pricing calculator for `asia-east2`; do not rely on numbers in this file.

- Pause: `gcloud compute instances stop k8s-lab-cp1 k8s-lab-worker1 k8s-lab-worker2 --zone asia-east2-a`
  (disks still bill). Start again with `start`. Terraform will not fight a stopped VM.
- Destroy everything in the cluster root (keeps the bucket and its state history):

```sh
cd terraform/environments/gcp-lab/cluster
terraform plan -destroy -out=destroy.tfplan       # read it
terraform apply destroy.tfplan
```

- The bucket stays (`prevent_destroy`). Removing it is a deliberate manual decision.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `Error 403 ... API has not been used` | Run bootstrap first, or wait a minute after enabling APIs |
| `Error acquiring the state lock` | Another run is active, or a crashed run left a lock; `terraform force-unlock <ID>` only when you are sure |
| IAP SSH timeout | Firewall `k8s-lab-allow-iap` missing, or your user lacks IAP-secured Tunnel User |
| `apt` hangs on a node | Cloud NAT disabled or still provisioning |
| Pods on different nodes cannot talk | Calico pool CIDR mismatch or `ipip` blocked; check `k8s-lab-allow-internal` |
| Plan wants to replace all VMs | You changed something immutable (zone, image, disk size down, scheduling) |
