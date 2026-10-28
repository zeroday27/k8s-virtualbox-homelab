# Image qualification contract

Images have a source architecture and hypervisor-specific artifacts. A VirtualBox
ARM64 ISO/base VDI is not interchangeable with a Proxmox x86_64 cloud-init template.
The common contract is the resulting guest behavior and provenance.

Each promoted image record must contain:

- Official source URL, signed-checksum verification result and source SHA256.
- OS/release/architecture, immutable build ID, build recipe/tool versions and SBOM.
- Hypervisor artifact locator and digest or template provenance, source host,
  firmware/Secure Boot mode, minimum root disk size and supported CPU baseline.
- Installed cloud-init/Python/sudo/SSH prerequisites and required guest agent.
- Qualification evidence for boot, network, trusted SSH identity, sudo, time,
  security baseline, containerd, cgroups, CNI and node restart.

`image.sha256` in this initial contract identifies the verified source artifact;
`template.sha256` must refer to the same source provenance. It is not a digest of
an entire mutable Proxmox VM. `build_id` connects that source to the reviewed build
manifest and template. A later image factory must produce signed attestations
and artifact digests before calling the supply chain verified.

Before cloning: remove cloud-init instance state, reset machine-id and SSH host
keys using the selected OS's documented generalization procedure, and power off.
First boot must generate fresh identities. Never distribute administrator private
keys, passwords, kubeconfigs, join tokens, etcd membership or cluster PKI in a base
image. Verify regenerated identity on two clones before promotion.

The Proxmox adapter expects an existing generalized UEFI template with cloud-init,
Python, sudo and QEMU guest agent installed. The template root disk must not be
larger than any requested clone root disk; resizing cannot shrink it. The adapter
currently requires a tested Secure Boot template and x86_64 CPU baseline.

For VirtualBox ARM, use Ubuntu Server ARM64 media; not AMD64 or Raspberry Pi media.
Oracle's built-in unattended installation is unavailable on ARM. Qualify Ubuntu
autoinstall/NoCloud or a generalized base VM before implementing that adapter.

The [VirtualBox ARM64 workflow](virtualbox-arm64.md) provides guarded guest
generalization and private per-clone seed generation for a lab bootstrap image.
Build artifacts and validation evidence stay outside public Git. A complete image
factory, signed artifact attestations and Proxmox image builds remain later stages.
Offline sites need verified mirrors of the installer, packages, runner wheels,
Kubernetes binaries, container images and chart artifacts, with off-site copies.
