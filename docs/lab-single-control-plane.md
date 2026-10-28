# Three-node VirtualBox learning lab

Default profile: `specs/lab-virtualbox-single.json`. It defines one control-plane
node and two workers, using Ubuntu Server ARM64, Calico and pinned Kubespray.
The optional five-node example remains `specs/lab-virtualbox.json`.

| Node | vCPU | RAM | Dynamic root disk |
| --- | ---: | ---: | ---: |
| cp1 | 2 | 2 GiB | 20 GiB |
| worker1 | 1 | 2 GiB | 20 GiB |
| worker2 | 1 | 2 GiB | 20 GiB |
| Total | 4 allocated | 6 GiB | 60 GiB virtual capacity |

## Endpoint and networking

`components.api_endpoint: node` connects directly to the sole control plane.
The legacy `network.api_vip` field holds that control-plane address, even though
no virtual IP is created. This mode is restricted to single-control-plane labs;
production and VIP modes retain their separate-address and topology guards.
The generated Kubespray variables disable kube-vip and the local API proxy and
use the direct address for the API endpoint and certificate SANs.

Example addresses: cp1 `192.168.56.11`, worker1 `.21`, worker2 `.22`; API
`192.168.56.11:6443`. Verify these do not conflict with existing routes or DHCP.
NAT provides the default route and outbound downloads. A second, host-only NIC
carries SSH and node traffic, with kubelet and Calico bound to that interface.
MetalLB is disabled initially; add it as a later application networking exercise.

The control plane is a single point of failure. This profile can teach worker
rescheduling, but it cannot demonstrate API/etcd quorum failover.

## Validate and preview

```sh
make preview
make plan
# Explicitly review the optional HA profile:
make plan SPEC=specs/lab-virtualbox.json
```

The Terraform root computes intent only. It does not create VirtualBox VMs.
The renderer emits a preview until qualified artifacts and matched VM facts are
available. Candidate images and release gates remain intact.

## Small-guest memory and SSH identity

The lab installer disables kernel crash dumps and adds a lab-owned GRUB filter
that removes crash-kernel memory reservations while preserving other boot
arguments. This policy applies only to lab seeds; production remains unchanged.
Verify usable RAM after reboot rather than lowering the existing memory check.
The [Ubuntu installer reference](https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html#kernel-crash-dumps)
documents the crash-dump option.

Verify SSH host keys after the installed guest's first boot: cloud-init can
regenerate installation-time keys. Use the trusted local console or an explicitly
read-only recovery boot to establish trust. Keep strict host-key checking enabled.
Quote SSH configuration paths containing spaces. With EFI, existing boot entries
can take priority over the VM's device order; inspect and preserve the original
EFI boot order before selecting recovery media.

## Disposable VM before the template

1. Check live host RAM pressure, free storage, VirtualBox support and routes.
2. Use a uniquely named private runtime directory and dedicated host-only
   network. Do not reuse or modify unrelated VMs, disks, networks or keys.
3. Verify the Ubuntu ARM64 source checksum against its signed-checksum receipt.
4. Boot one disposable 2-vCPU, 2-GiB VM with a dynamic 20-GiB root disk, NAT,
   host-only networking and a unique per-install seed.
5. Prove installed ARM64 boot, static lab addressing, NAT egress, trusted SSH,
   sudo, Python, time synchronization and read-only Ansible preflight.
6. Reboot once and recheck access and address persistence. Shut down and remove
   only resources identified in this proof's ownership record. Retain evidence.
7. Build the reusable generalized base only after reviewing that evidence.

A successful disposable boot does not qualify containerd, Calico, Kubernetes,
clone identity or recovery. Keep those acceptance gates separate. One role-neutral
base will later serve all nodes, with unique IDs, keys, MACs and first-boot seeds.
Ansible owns the OS baseline; Kubespray owns containerd/Kubernetes/CNI. Do not
introduce a parallel hand-written kubeadm installer.
