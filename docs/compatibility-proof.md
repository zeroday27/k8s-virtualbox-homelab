# VirtualBox ARM64 compatibility proof

Technical evaluation dated 2026-10-26. This is a proposed experiment and
implementation contract, not evidence of a successful VM or Kubernetes build.
No VM, virtual disk, network or guest has been created by this scaffold.

## Compatibility findings

| Question | Evidence | Decision |
| --- | --- | --- |
| macOS 27.0.1 on Apple Silicon | Oracle's VirtualBox 7.2 installation page lists Apple Silicon macOS 13–26; 27 is absent | Exact host support is unconfirmed. A working CLI does not prove VM execution or vendor support. Do not change host OS or VirtualBox during planning. |
| Ubuntu Server 26.04 LTS ARM64 | Ubuntu publishes `ubuntu-26.04.1-live-server-arm64.iso` | Candidate installer; pin its SHA256 and verify the signed checksum file before use. No ISO downloaded yet. |
| Guest platform | Oracle requires ARM guests on ARM hosts; installed CLI advertises `--platform-architecture=arm` and `Ubuntu_arm64` | Use generic Ubuntu ARM64 type when a 26.04-specific type is absent. Confirm EFI and storage defaults in `showvminfo`. Boot remains untested. |
| Unattended install | Oracle says its unattended installer is unavailable on ARM | Evaluate Ubuntu Subiquity autoinstall with cloud-init NoCloud; do not use `VBoxManage unattended install`. |
| Host-only networking | Oracle replaces host-only adapters with host-only networks on recent macOS | Use `hostonlynet`, not `vboxnet0`. Host interface exists dynamically while attached VMs run. |
| Terraform provider | ARM64 host binary exists, but released VM schema/code targets older guest/network interfaces | Reject the unchanged release for this topology; see below. |

Primary sources:

- [Oracle installation and ARM limits](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/installation.html)
- [Oracle host-only networking](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/networkingdetails.html)
- [Oracle VBoxManage reference](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/vboxmanage.html)
- [Ubuntu ARM64 Server images and signed checksums](https://cdimage.ubuntu.com/releases/26.04/release/)
- [Subiquity autoinstall delivery](https://canonical-subiquity.readthedocs-hosted.com/en/latest/tutorial/providing-autoinstall.html)
- [cloud-init NoCloud seed format](https://cloudinit.readthedocs.io/en/latest/reference/datasources/nocloud.html)

The last two documents describe the intended seed mechanism; validate their
current schema and the actual 26.04 installer behavior during implementation.
Installer media must be the standard ARM64 live-server ISO, not AMD64, Raspberry
Pi, desktop, or `+largemem` media. Do not confuse an ARM host executable with
support for ARM virtual machines or a tested Ubuntu/Kubernetes combination.

## Terraform integration decision

GitHub's latest release and the Terraform Registry both advertise
`0.2.2-alpha.1` (2021-09-21), including a `darwin_arm64` archive. Availability is
confirmed at the metadata level; the provider binary has not been installed or
run here. The repository's `main` revision inspected was
`58d5bdf02d52c4f757de000a8d2e2eabb6729118` (2024-07-25).

The released `virtualbox/resource_vm.go`:

- Sets `vm.OSType = "Linux_64"` inside `tfToVbox`.
- Accepts `hostonly`, mapping to `NICNetHostonly` and requiring `host_interface`.
  It has no `hostonlynet` mapping or configurable ARM platform/guest OS field.
- Uses a disk-image cloning workflow and stores gold/machine data under
  `~/.terraform/virtualbox/`, rather than the selected lab runtime root.

This source inspection is enough to reject the unchanged release before VM
creation. Current main is not a tested substitute for a released provider.
No maintained fork has been qualified; do not imply all forks were evaluated.

Evidence:

- [Release assets](https://github.com/terra-farm/terraform-provider-virtualbox/releases/tag/v0.2.2-alpha.1)
- [Registry platforms](https://registry.terraform.io/v1/providers/terra-farm/virtualbox/versions)
- [Registry darwin_arm64 download metadata](https://registry.terraform.io/v1/providers/terra-farm/virtualbox/0.2.2-alpha.1/download/darwin/arm64)
- [Released VM implementation](https://github.com/terra-farm/terraform-provider-virtualbox/blob/v0.2.2-alpha.1/virtualbox/resource_vm.go)
- [Current source at inspected revision](https://github.com/terra-farm/terraform-provider-virtualbox/blob/58d5bdf02d52c4f757de000a8d2e2eabb6729118/internal/provider/resource_vm.go)

**Proposed integration:** Terraform owns the topology and invokes a small,
documented VBoxManage adapter after the direct CLI proof passes. Prefer this to
maintaining a custom Go provider for five learning VMs. This is a deliberate
fallback with limited drift detection and no native VM import semantics.
If native Terraform VM resources are required, stop at this decision and qualify
a fork or custom provider before continuing.

The adapter must eventually satisfy these requirements:

1. Stable per-node Terraform keys; explicit runtime root outside the checkout;
   local backend/state and private ownership metadata outside Git.
2. Record VM UUID, disk paths, network ownership and configuration fingerprint.
   Refuse to adopt/delete a VM by matching its name alone. Pre-existing networks
   and the base image are not implicitly owned by node resources.
3. Bounded CLI calls, sequential creates, meaningful exit codes and cleanup of
   partial creates. Reruns must inspect existing UUIDs before creating anything.
4. A read-only audit using `showvminfo --machinereadable` before plan/apply,
   including missing VMs, NICs, CPU/RAM and disk attachment drift. Terraform
   `terraform_data` alone cannot refresh external VM state; an empty plan alone
   is insufficient evidence of convergence.
5. Explicit safe replacement and destruction procedures. No broad inventory
   deletion, shared-network deletion, or recursive cleanup of runtime roots.
6. Prove create, boot, shutdown, restart, full clone, audit, repeat run and
   deletion of only the disposable proof VM. Do not attach the rejected provider
   to an ARM VM and hope to repair it with later commands.

## Resource and storage gates

Keep the five-node sizing at 3 × (2 vCPU, 2 GiB, 16 GiB) plus
2 × (1 vCPU, 2 GiB, 20 GiB): 8 allocated vCPUs, 10 GiB RAM, 88 GiB root capacity.
A one-vCPU worker is a constrained learning choice; do not bypass kubeadm
preflight failures if the selected version requires more. Increase sizing or
reduce the exercise workload if measured pressure requires it.

| Stage | Guest allocation | Host free-space gate | Evidence required |
| --- | --- | --- | --- |
| Planning | None | None | Read-only inventory and source review |
| One-VM proof | 2 vCPU, 2 GiB, one dynamic 16 GiB disk | At least 55 GiB before download/create | Allows 16 GiB disk, roughly 3 GiB ISO and temporary seed/logs while retaining 30 GiB; memory pressure stable and swap not growing |
| Five-node lab | 8 vCPU, 10 GiB, 88 GiB dynamic disks | At least 100 GiB; prefer 120 GiB | Host-only/DHCP proof, installer and integration gates pass; close competing applications first |

These are operational gates, not guarantees that all VDIs can fill. Estimate
40–55 GiB guest data, about 3 GiB installer, 6–10 GiB retained base,
2–5 GiB temporary files, 5–10 GiB local backups, and 30 GiB macOS reserve:
roughly 86–113 GiB total. A fully grown 88 GiB cluster plus a 16 GiB base,
installer, temporary files and reserve needs over 140 GiB before larger backups.
Snapshots and full clones can grow beyond the small-lab estimate.

Measure with `df` and `du` on the actual runtime filesystem before/after each
stage. Keep at least 30 GiB host free throughout; stop allocation if approaching
that limit. Keep only a clean base and five independent node disks, plus at most
one short-lived exercise snapshot. Growing disks can be expanded later; shrinking
VDIs is not the capacity plan. External APFS SSD storage is an alternative after
checking its capacity and reliability; never reformat or delete data automatically.

Guest RAM allocation is already aggressive on 16 GiB. Compressed memory and
system-wide free-memory percentages do not mean 10 GiB is available for VMs.
Close competing workloads, sample memory pressure and swap over several minutes,
and stop the proof if swap grows steadily. Reassess again before five VMs.

## Network gate

Proposed layout remains `192.168.56.0/24`: Mac `.1`, API `.10`, control planes
`.11–.13`, workers `.21–.22`, MetalLB `.200–.219`. Proof uses `.11`; it must be
removed before cp1 takes that address. Pod `10.244.0.0/16` and Service
`10.96.0.0/12` are also subject to route checks, including VPN routes.

Inspect all four inventories: `list hostonlynets`, `list hostonlyifs`,
`list dhcpservers`, and `list vms`. An empty modern-network inventory does not
imply no legacy DHCP configuration exists. In particular an enabled legacy
`HostInterfaceNetworking-vboxnet0` pool `.101–.254` overlaps the application pool.
Do not treat it as a proven active collision, but resolve its ownership and
whether to disable it, or choose another non-overlapping /24, before creation.
No existing DHCP/network configuration is changed during planning.

For a new owned network, the candidate managed range is `.1–.9` with mask
`255.255.255.0`; Oracle says the host takes the lowest address. Confirm actual
host address and DHCP lease bounds after creation. Keep DHCP out of node/VIP
ranges. Static guests use NAT on NIC1 and host-only on NIC2, matched by recorded
MACs in netplan. Only NAT supplies a default route/DNS. An active VPN's default
route is not an address overlap, but may still affect egress or local reachability.

## One-VM proof procedure — proposed, not executed

Use a dedicated `k8s-proof-arm64` VM and an explicit UUID/ownership record.
Keep all ISO/seed/disk/log artifacts under the private runtime root. Do not
create full-cluster resources as a side effect of this experiment.

1. Recheck host storage, memory/swap trend, routes and inventories. Resolve
   the DHCP overlap. Record the macOS 27 support uncertainty; a proof pass
   demonstrates observed behavior only, not Oracle support certification.
2. Download the selected Server ARM64 installer and signed SHA256 files.
   Verify signature using an independently trusted Ubuntu signing key, then
   verify ISO digest. Record URL, checksum and installer version; never infer
   validity from a matching filename. No base image is trusted before this step.
3. Build a NoCloud seed ISO labelled `cidata`, containing `user-data` and
   `meta-data` with a unique instance ID. Use a tested `autoinstall:` v1 document,
   SSH public key, disabled SSH password login, Python and matching netplan.
   Keep password hashes and any seed with credentials outside source control.
   Supply the installer's `autoinstall` kernel argument through a reproducible
   ARM EFI boot path (a remastered installer is an option). Merely attaching a
   seed does not prove headless boot automation. Check seed tooling availability
   and record the exact boot method before starting the VM.
4. Create one ARM VM with 2 CPUs, 2048 MiB RAM, EFI, VMSVGA, a dynamic 16 GiB
   root disk and the verified installer/seed. Choose storage/NIC types supported
   by the ARM platform and record the actual settings. Start headless and collect
   installer/serial logs. Require unattended completion and SSH readiness within
   a bounded installation window (initial budget 30 minutes, then diagnose).
5. Verify `uname -m` is `aarch64`, Ubuntu is `26.04`, RAM is at least 1800 MiB,
   disk layout fits 16 GiB, SSH host key is verified, and identities are unique.
   Check Mac→`.11` SSH, guest→Mac, HTTPS/DNS over NAT and one default route.
   Reboot and repeat; do not install Guest Additions solely to obtain an IP.
6. Temporarily add `.10/32` then `.200/32` to the guest host-only NIC, one at a
   time. Serve a tiny HTTP response bound to the alias and curl it from the Mac.
   Check ARP/neighbor learning and guest firewall behavior. Remove aliases and
   stop the server after testing. These aliases test address advertisement and
   reachability only; they do not validate kube-vip, MetalLB or failover.
7. Check kernel modules, forwarding, cgroups v2, swap and containerd CRI with
   systemd cgroups. Select exact ARM64 Kubernetes/runtime/add-on versions from
   their compatibility guidance. In the disposable VM, run a single-node
   kubeadm/CNI smoke test if the base boot/network gates passed; confirm runtime,
   DNS and a tiny pod work at 2 GiB. Do not claim stacked etcd HA from this test.
8. Return to a clean OS base (or reinstall), generalize cloud-init state,
   machine-id and host keys while powered down, then test a full clone as a
   **replacement**, with only one running proof guest. Verify fresh MAC,
   machine-id, cloud-init instance ID, hostname and SSH keys after first boot.
   Never clone joined etcd/Kubernetes identity. Account for temporary duplicate
   disk space before cloning and keep a clean base only if capacity permits.
9. Prove the selected lifecycle integration and its audit behavior. Save a
   sanitized result table: command/version, pass/fail, elapsed time, actual disk
   usage, host pressure/swap trend and unresolved issues. Shut down and delete
   only the UUID and disk positively identified as disposable; preserve any
   intentionally retained base. Verify no proof VM remains before scaling.

Installed 7.2 CLI help confirms these relevant command shapes. They are examples
for the later proof, **not commands executed in this planning pass**; storage,
installer attachment and error handling still need implementation:

```text
VBoxManage hostonlynet add --name=k8s-ha --netmask=255.255.255.0 --lower-ip=192.168.56.1 --upper-ip=192.168.56.9 --enable
VBoxManage createvm --name=k8s-proof-arm64 --platform-architecture=arm --ostype=Ubuntu_arm64 --basefolder=<private-machines-directory> --register
VBoxManage modifyvm <proof-uuid> --cpus=2 --memory=2048 --firmware=efi --graphicscontroller=vmsvga --nic1=nat --nic2=hostonlynet --host-only-net2=k8s-ha
VBoxManage showvminfo <proof-uuid> --machinereadable
VBoxManage startvm <proof-uuid> --type=headless
```

A single VM cannot demonstrate guest-to-guest forwarding, API VIP movement,
etcd quorum or MetalLB speaker failover. After it passes, use the first two
planned cluster nodes for an L2/ARP movement check before creating the remaining
three. Three control planes are required for the quorum exercise.

## Implementation after the proof

1. Record a tested version/digest matrix and the chosen adapter/provider decision.
   Implement local state placement, ownership checks and image/seed generation.
2. Create cp1 and cp2 sequentially; prove inter-guest traffic and alias movement.
   Then create cp3 and the workers. Confirm all addresses, identities, time and
   SSH access from generated inventory. Change the example MetalLB YAML if the
   network changes; it does not automatically follow a Terraform override.
3. Ansible configures OS and containerd, installs pinned packages, then performs
   cp1 kube-vip/kubeadm bootstrap and sequential stacked-etcd joins. Test the
   chosen kube-vip release's initial kubeconfig handling and `controlPlaneEndpoint`.
   Install Flannel over the host-only NIC and join workers with explicit node IPs.
4. Require five Ready nodes, three healthy etcd members and repeatable Ansible
   before adding MetalLB worker advertisements and a two-replica HTTP service.
5. Measure one-control-plane and one-speaker failover, restore each failed node
   before another failure, then test drain/reschedule and disposable etcd restore.
   Leave storage replication and heavy monitoring out of this profile.

The README contains the full cluster acceptance gates. This experiment does not
authorize full-cluster deployment; present its actual results before scaling out.
