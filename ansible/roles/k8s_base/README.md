# Kubernetes base

The `k8s_base` role prepares the single-control-plane, two-worker Ubuntu 26.04
ARM64 or AMD64 lab. It owns upstream binary installation and containerd configuration.
Kubeadm owns subsequent cluster bootstrap and upgrades. Do not combine this
profile with the separate Kubespray bundle in `versions.lock.json`.

## Locked components

`ansible/vars/k8s-base.bom.json` is the installation BOM. Downloads require
SHA256 checksums; Calico and pause images use immutable OCI index digests with
verified ARM64 and AMD64 children. This is a candidate installation BOM, not a complete
SPDX/CycloneDX inventory or evidence of runtime qualification.

| Component | Version | Nodes |
| --- | --- | --- |
| containerd | 2.4.2 | All |
| runc | 1.5.2 | All |
| crictl | 1.37.0 | All |
| kubeadm / kubelet | 1.37.2 | All |
| kubectl | 1.37.2 | Control plane |
| Kustomize | 5.8.3 | Control plane |
| Calico | 3.33.0 | Staged on control plane; CNI later runs on all nodes |

APT host dependencies follow the configured Ubuntu repositories. Their exact
installed versions must be recorded during runtime qualification. Kubeadm's
etcd 3.7.0-0 and CoreDNS v1.14.6 defaults were confirmed with the official
kubeadm v1.37.2 binary. Their exact OCI index digests are locked in the BOM and
used as tag@digest image overrides. Both index child manifests were verified.
Native kubeadm also validated the rendered init/join configs and returned these
exact etcd/CoreDNS references from `config images list --config`.

## Variables and loops

Put site overrides in the ignored inventory file
`ansible/inventory/lab/group_vars/lab_nodes/90-site.local.yml`.
Defaults live in `defaults/main.yml`; artifact versions and hashes belong in the
BOM and must be updated together. `artifacts_by_arch` selects the guest CPU
through `aarch64 -> arm64` or `x86_64 -> amd64`; unsupported CPUs fail.
The artifact loop in `tasks/install.yml`
selects all-node versus control-plane tools; `tasks/artifact.yml` loops through
files inside each verified artifact.

| Variable | Default / meaning |
| --- | --- |
| `k8s_base_node_interface` | OS baseline interface, normally `lab0` |
| `k8s_base_node_ip` | Static IPv4 discovered on that interface |
| `k8s_base_pod_cidr` | `10.244.0.0/16`, must match baseline firewall |
| `k8s_base_service_cidr` | `10.96.0.0/12`, must not overlap pods/node |
| `k8s_base_cni_transport` | `ipip`; BGP and IPIP match existing firewall |
| `k8s_base_access_verified` | Inherits `baseline_access_verified`, false by default |

The role loads overlay, br_netfilter and ipip, enables IPv4 forwarding and bridge
filtering, configures containerd CRIv1/systemd cgroups, and installs standard
kubeadm kubelet units. Kubelet stays stopped and disabled until bootstrap.
The baseline still owns SSH, host firewall, swap, AppArmor and OS hardening.
No host firewall rules are broadened by this role.

## Commands

Run from `ansible/` using the repository virtual environment:

```sh
../.venv/bin/ansible-playbook playbooks/01-k8s-base.yml --check --diff \
  -e '{"baseline_access_verified":true}'
```

Check mode validates access/platform, ownership, swap and network contracts,
predicts host prerequisites, and previews containerd and Calico configuration.
It deliberately skips binary installation, extraction, service activation and
remote Kustomize build. It cannot prove runtime readiness.

After reviewing the check, install the base on the canary first:

```sh
../.venv/bin/ansible-playbook playbooks/01-k8s-base.yml \
  --limit control_plane -e '{"baseline_access_verified":true}'
../.venv/bin/ansible-playbook playbooks/01-k8s-base.yml \
  --limit workers -e '{"baseline_access_verified":true}'
```

The play uses `serial: 1` and stops on failure. Existing package-managed runtimes,
unowned files and joined nodes are rejected; it is not an upgrade playbook.
Verify `crictl info`, installed versions, units and reboot behavior before
bootstrap. NetworkReady may remain false until the CNI is installed.

## Calico phase

Base preparation vendors the checksum-locked raw manifest and builds the
Kustomize overlay under `/opt/k8s-base/calico`. It selects each node’s Kubernetes InternalIP,
pod CIDR, IPIP Always and VXLAN Never, and pins every Calico image by digest.
The raw-manifest installation is deliberate for this small lab, without Typha;
it requires explicit manifest lifecycle management rather than an operator.

After the explicit bootstrap phase below creates admin.conf:

```sh
../.venv/bin/ansible-playbook playbooks/03-k8s-calico.yml \
  -e '{"baseline_access_verified":true}'
```

This explicit play applies the rendered resources with server-side ownership.
Check rollout of calico-node and calico-kube-controllers and test cross-node pod
traffic, DNS and policy before calling the cluster ready. The base play never
runs kubeadm init/join, opens the firewall, or applies Calico automatically.

## Bootstrap phase

Run against the complete inventory; `--limit` is rejected by the all-node
preflight to prevent bootstrapping before a skipped node has been checked.

```sh
../.venv/bin/ansible-playbook playbooks/02-k8s-bootstrap.yml --check --diff \
  -e '{"baseline_access_verified":true}'
```

Check mode renders the init plan and worker discovery plan without tokens,
cluster membership, configuration files or service changes. With base tools
missing it cannot prove kubeadm preflight, CRI readiness or API connectivity.
After the base canary and workers are installed and qualified, the explicit
bootstrap command is:

```sh
../.venv/bin/ansible-playbook playbooks/02-k8s-bootstrap.yml \
  -e '{"baseline_access_verified":true}'
```

The three plays validate every node first, initialize one control plane, and
join workers serially. The static management IP is used for advertiseAddress,
API endpoint and kubelet node-ip. Containerd and kubelet both use systemd cgroups.
Control-plane static pod images use digest patches; etcd and CoreDNS use pinned
kubeadm image overrides. Kube-proxy is set to its verified digest after kubeadm
creates the add-on. No default long-lived discovery token is generated by init.

Each worker gets a 10-minute discovery token and the SHA256 hash of the trusted
control-plane CA public key. Join tasks hide credentials, write root-only files,
remove join.yaml and revoke the token in `always`, including join failure.
The token TTL limits exposure if the control plane becomes unavailable during
cleanup. CA verification is never skipped. Admin kubeconfig stays root-only on
the control plane and is not copied to the controller or workers.

A successful node gets a credential-free receipt. A repeated bootstrap checks
version, architecture, address, endpoint and network identity before skipping
existing membership. Partial or unowned membership stops for manual review;
there is no automatic reset, reinitialization or upgrade.

Run the separate Calico play next. It compares the rendered resources with the
API before server-side apply, waits for Calico, CoreDNS and kube-proxy rollouts,
and requires all three inventoried nodes to be Ready. Cross-node traffic,
NetworkPolicy and DNS functional tests remain runtime acceptance gates.

## CPU architecture and qualification

The same roles support Linux ARM64 and Linux AMD64 (x86_64), including mixed-CPU
inventory. Each host selects its own binary URLs and checksums using guest facts.
All selected OCI index pins contain both platforms, so the runtime selects the
matching child image. Ordinary Kubernetes configuration is shared across CPUs.

The OS image and virtual disk must match the destination CPU. Do not reuse the
ARM64 VirtualBox VDI on an x86 host. Use a separately built Ubuntu 26.04 AMD64
image, then verify SSH, sudo, network interface, firewall and OS baseline. The
current inventory is ARM64; for an x86 host override
`baseline_expected_architecture: x86_64` and set its observed interface and
private site addresses. The base role detects CPU itself; never force ARM64
facts on x86. The controller can run on either architecture.

ARM64 guest check mode and native kubeadm configuration validation have been
performed. AMD64 artifact locks, image manifests, selection and configuration
contracts have static validation only; no x86 guest is available for runtime
qualification. Runtime/containerd/CNI/reboot checks must pass independently on
x86 before calling that profile qualified. Workload images also need the right
CPU platform or scheduling constraints such as `kubernetes.io/arch: amd64`.

Calico uses `kubernetes-internal-ip` so hosts may have different interface names.
Kubelet publishes the static address selected from each host’s declared interface;
Calico follows that address rather than applying the control plane’s NIC name
to every worker. See the [Calico autodetection documentation](https://docs.tigera.io/calico/latest/networking/ipam/ip-autodetection).
