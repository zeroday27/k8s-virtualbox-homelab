# ARM64 lab template and clone workflow

This workflow creates a role-neutral Ubuntu ARM64 lab bootstrap image. Keep the
sealed VM powered off and full-clone it for each node. The same base supports the
single control plane and both workers; Kubernetes assigns roles afterward.
A template passing these checks remains a lab candidate until OS baseline,
containerd, Kubernetes and CNI qualification also pass.

## Build and seal

1. Verify official ARM64 installation media against signed checksums. Use
   `scripts/prepare_virtualbox.py` to prepare a private autoinstall recipe and
   inspect its proposed commands. Install a fresh, isolated builder with trusted
   console access. Avoid importing any joined-node disk or cluster credentials.
2. In the builder, create `/etc/homelab-image-build.json` containing a unique
   `build_id`, `purpose: role-neutral-lab-template`, source commit and installer
   SHA256. Record the exact recipe hashes and hypervisor settings privately.
3. Finish the installed system's first boot, detach installation media, and prove
   architecture, usable memory, DNS/HTTPS, NAT default route, management address,
   time sync, trusted SSH and passwordless sudo. Obtain the actual post-first-boot
   public host key from the local console before enabling strict SSH verification.
4. Review `scripts/generalize_virtualbox_guest.py`, transfer it to the builder,
   and run **inside that disposable guest** as root with `--build-id <build-id>`.
   It requires the matching marker and refuses a guest with Kubernetes state.
   It cleans cloud-init, machine ID, host keys, bootstrap authorized keys, installer
   networking, leases, logs and random seed, preserves root mounts, then powers off.
   It installs early systemd link rules for the fixed VirtualBox virtio PCI slots
   (NIC1 at 00:08.0, NIC2 at 00:09.0) and refreshes initramfs. This avoids a
   first-boot rename race when cloud-init finds already-active interfaces. Keep
   these NIC slots and virtio models when cloning; another layout needs a new
   image profile and runtime validation.
5. Require its JSON receipt and confirm power-off from the host. Detach all seed
   media and the builder's management NIC; record the sealed VDI SHA256 and disk
   UUID in a private manifest. Never boot this base again; rebuild if it is booted.

Ubuntu's installer may disable cloud-init after completing bootstrap. The sealer
accepts only the explicitly recognized installer marker and reviewed locked blank
password warning after final-stage completion. Other incomplete/error states stop
sealing. It removes installer overrides so clone NoCloud networking can run.

## Prepare each clone

Use the repository virtualenv, which supplies PyYAML. Choose a fresh UUID and a
separate administrator public key for each disposable validation clone:

```sh
.venv/bin/python scripts/prepare_virtualbox_clone.py \
  --spec specs/lab-virtualbox-single.json --node worker1 \
  --instance-id <fresh-clone-uuid> --public-key <administrator.pub> \
  --output .generated/worker1-seed
xorriso -as mkisofs -V cidata -J -r -o .generated/worker1-seed.iso \
  .generated/worker1-seed
```

The command only writes private files and refuses an existing destination. Review
`identity.json`, then create a registered **full** clone with its fresh UUID and
without the VirtualBox `link` option. Set NIC1 to NAT and NIC2 to the reserved
host-only network, using the exact two MAC addresses in `identity.json`. Attach
the seed ISO and boot from the cloned disk. The seed configures NAT DHCP plus the
node's static management address with no second default route. Never boot two
clones with the same node/IP seed. Use a private spec for actual network changes.

Connect the ARM serial console to a private log before boot. The seed emits the
new ED25519 public key between its `host_key_marker` BEGIN/END markers after the
first-boot SSH module has run. Pin that key with StrictHostKeyChecking enabled.
Quote paths containing spaces inside SSH configuration files.

## Acceptance and cleanup

Validate two independent full clones. Require cloud-init status `done` with exit
zero; expected hostname, instance UUID, addresses and NAT default route; unique
machine IDs, all SSH public host keys and NIC MACs, distinct from the builder.
Verify SSH/sudo, DNS, verified HTTPS, time sync and usable RAM. Prove the builder's
bootstrap key is rejected. Reboot each clone: its boot ID must change while its
machine ID, keys, instance ID and management address persist.

Confirm the base stayed powered off and its VDI checksum is unchanged. Record
clone disk UUIDs and independent base parentage. Delete only the owned validation
clones, their seed media, temporary private keys and isolated proof network.
Retain the sealed base, manifest and private evidence. Production qualification,
signed image attestations and the native Terraform VirtualBox adapter remain
separate gates; do not flip release qualification flags from this guest proof.
