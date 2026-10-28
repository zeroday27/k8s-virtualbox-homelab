# Architecture and extension contract

## Objective and boundaries

Build replaceable on-premises Kubernetes environments from versioned intent:
Terraform provisions the required VMs; Ansible establishes the OS baseline;
pinned Kubespray manages Kubernetes lifecycle; GitOps reconciles platform add-ons.
Recovery reconstructs infrastructure and restores application state from independent
backups. The deliverable is a reproducible, tested release, not a universal claim
that every hypervisor, image or plugin works.

The initial engine bundle is Kubespray v2.32.0, commit
`9751ea6f63244e433a7a6263d9ecf381e57bb8e9`, Kubernetes 1.36.4 and containerd/CNI
versions from that upstream commit. Ubuntu 26.04 is in its stated OS support.
This is upstream compatibility evidence, not our runtime qualification.

## Ownership

| Layer | Owns | Does not own |
| --- | --- | --- |
| Cluster specification | Node classes, addresses, architecture, image identity, component intent, security and RPO/RTO | Credentials or claims that capacity exists |
| Image factory | Generalized source-to-artifact provenance, bootstrap prerequisites, qualification | Live cluster membership or secrets |
| Terraform adapter | VM identity, sizing, disks, NICs, placement, lifecycle observations | SSH shell provisioning or kubeadm execution |
| OS baseline | SSH authentication policy, selected kernel protections, time sync, auditing and bounded host logs | Unreviewed benchmark remediation, CNI firewall rules or automatic reboots |
| Kubespray | Kubernetes bootstrap/upgrade, containerd, CNI, control-plane endpoint and etcd mode | Customer applications and independent backup storage |
| GitOps | MetalLB, Gateway API implementation, certificates, policy, monitoring, logs and CSI integrations | Hypervisor lifecycle or secret plaintext |
| Recovery operations | Fencing, isolated restore, data validation, cutover and failback | Automatic failover with unproven data consistency |

## Specification workflow

The `onprem/v1alpha1` JSON schema is strict; unknown fields are errors. Classes
supply repeatable CPU/RAM/root/data-disk sizes, and nodes select a class with
stable names, role, IP, interface, physical placement and failure domain. Add
another class for an exceptional node rather than editing generated resources.

The compiler validates structure and semantic relationships before generating
private inputs. It checks address uniqueness, CIDR overlap, service pool separation,
image/host architecture, control-plane counts, production failure domains and
required security/DR intent. It cannot discover available IPs, audit a real rack,
prove DNS/MTU or certify a disk performance target from JSON alone.

The top-level `terraform/` root computes normalized intent and budgets with no
provider and no VM creation. Proxmox consumes the same contract under its own root.
Provider roots stay separate: Terraform cannot dynamically substitute provider
resource types from a string. Add an adapter with the same inputs/observations
and its own provider pin, lock file, backend and lifecycle tests.

## Adapter input and observation contract

Input: normalized stable node keys; role; CPU/RAM/root/data disks; management IP;
interface; image key/build; architecture; physical host and failure domain.
Site-specific mapping adds datastore, bridge/VLAN, template locator and VM IDs.
Credentials use the provider's supported environment/secret integration.

Output after apply/refresh: `provisioned_nodes`, keyed by node name, with nonempty
VM ID, expected IP, guest-observed IPs, actual hypervisor host and image build ID.
Use `terraform output -json` with a private backend to obtain these observations.
This output remains sensitive operational data even if marked nonsensitive by
Terraform. It contains no intended passwords or private keys.

The inventory compiler rejects missing/extra nodes, duplicate VM IDs, placement,
image or observed-IP mismatches. A planning inventory cannot silently become a
runtime inventory. The image build ID is operator-supplied provenance; current
code does not remotely attest guest disk content.

Every adapter must prove create, read/refresh, resize, start/stop, rebuild, import,
controlled replacement, partial-create recovery and targeted deletion on disposable
VMs. Test a second plan after apply. An adapter without native import/drift
semantics must disclose that limitation. The VirtualBox adapter remains unimplemented;
the old community provider's ARM binary alone does not qualify ARM VM networking.

## Proxmox implementation

The provider is pinned to `bpg/proxmox` 0.118.0. It full-clones a qualified template,
uses fixed memory, virtio NICs and stable per-node resource keys, applies public
SSH keys through cloud-init, and checks QEMU guest-agent IPv4 observations.
The example CPU baseline is configurable as `platform.cpu_model` (`x86-64-v2-AES`); verify every host supports it and
migration works before qualifying this adapter. Changing the template or CPU model
is an image/adapter release change, not an unattended production upgrade.

Production requires declared independent control-plane hosts. Verify shared storage,
rack/power/network dependencies separately: three host names do not establish site
resilience. The provider's VM firewall flag requires a reviewed Proxmox firewall
policy already in place; this scaffold does not create those rules. Preflight
that policy before allowing the first VM to start.

The adapter intentionally blocks production deployment while the bundle/image are
candidates. A dedicated disposable qualification root/state is a next implementation
step; it must exercise the same VM settings without promoting candidate artifacts
or touching production state. It is not implemented in this scaffold. Do not mark
an untested bundle qualified just to run the first proof.
`deployment_approved=true` alone cannot bypass qualification. It also uses static
`prevent_destroy=true`. That guard is not a backup and does not protect resources
removed from configuration. Handle legitimate decommission/replacement through a
reviewed change and recovery plan; never disable the guard across an environment
just to make a plan pass. Review provider updates for automatic reboot behavior.

## State and secret boundaries

Each site/cluster has a separate state key and single writer. Production uses a
backend outside the managed cluster with TLS, encryption, versioning, conditional
write locking, access control and independent recovery. The S3-compatible backend
example must be qualified against the actual storage product; compatibility with
object uploads alone does not prove correct locking. Do not place the only backend,
secret store or backup destination on the cluster it must recover.

Terraform state, plan JSON, inventories and cloud-init data may expose sensitive
values regardless of `sensitive=true`. Never generate private keys/passwords in
Terraform for convenience. Use existing public keys; secret-manager/Vault references
stay outside public examples. Ansible secret tasks require `no_log`, encrypted
private storage and disabled diff output for secrets. Release logs must be sanitized.

## OS and Kubernetes execution

The baseline is a conservative Ubuntu foundation, not a CIS certification claim.
Run read-only guest checks, verify trusted SSH host keys, key-based login, sudo and
console recovery, then canary the baseline with `serial: 1`. Its explicit access
gate is an operator acknowledgment, not automated proof of the recovery path.
SSH configuration is tested before reload; failed reconnection can require console
recovery because Ansible cannot roll back over a lost connection. Review effective
`Match` rules for the actual administrator source address.

Keep AppArmor enabled. The baseline prepares swap-off and conservative host
protections; Kubespray enforces runtime, swap and CNI prerequisites during cluster
installation. The lab can select a peer-scoped host-input nftables policy; it
leaves forwarding and NAT to the CNI. Review the actual Calico transport and prove
pod traffic plus host isolation on a canary before qualification. Broad firewall
remediation, detailed audit rules, patch orchestration and compliance certification
remain outside this baseline. See the [baseline role guide](../ansible/roles/os_baseline/README.md)
for variables, recovery and check-mode limitations.

Fetch Kubespray into a private directory using `scripts/fetch-kubespray.sh`. The
script verifies the immutable commit and never executes a playbook. Use a separate
venv installed from `ansible/kubespray.requirements.lock` with hash checking.
Execute its cluster, scale, upgrade and recovery procedures only after scope and
release qualification are established. Do not mix those dependencies into the
repository's static-validation venv.

Example operator sequence after qualification, with explicit private paths:

```text
specctl validate --spec <private-spec.json> --deployment
terraform -chdir=terraform/adapters/proxmox init -backend-config=<private-backend.hcl>
terraform -chdir=terraform/adapters/proxmox plan -var-file=<private-inputs.tfvars.json>
# Review the actual plan, placement and backups before apply.
# Export apply/refresh observations into a private JSON file.
specctl render --spec <private-spec.json> --facts <private-outputs.json> --output <new-private-inventory-dir>
# Run ansible/preflight.yml, then the guarded OS baseline on one canary.
# Use the pinned Kubespray runner and generated inventory/extra-vars afterward.
```

These are implementation procedures, not evidence that deployment has occurred.
The renderer does not execute Terraform, Ansible, Kubespray or GitOps.

## Component decisions

| Function | Lab | Production target | Owner |
| --- | --- | --- | --- |
| etcd | kubeadm static pods on control planes; upstream experimental mode | Default systemd etcd colocated with control planes | Kubespray |
| API endpoint | Direct control-plane IP for the default single-node lab; kube-vip ARP for the optional HA lab | kube-vip on an appropriate L2 domain or qualified external HA endpoint | Kubespray / external network team |
| CNI | Calico with explicit interface and NetworkPolicy exercises | Calico initially; Cilium requires another qualified bundle | Kubespray |
| Application LoadBalancer | MetalLB L2, worker announcements | MetalLB L2 or a separately qualified BGP design | GitOps |
| Application routing | Tiny Service exercises first | Gateway API plus a qualified controller and certificates | GitOps |
| Access and policy | Isolated learning credentials | OIDC/RBAC, restricted workload namespaces, documented system exceptions, Kyverno policy | Kubespray / GitOps |
| Storage | Ephemeral first; node-local only for learning | Qualified CSI against site storage; application-consistent protection | GitOps / storage operations |
| Observability | Small exercises | Metrics, alert delivery, centralized logs, audit retention and SLOs; traces as workload needs require | GitOps |

Additional component chart versions/digests and their reconciler definitions are
not implemented. `components.intent.json` records desired ownership only; a boolean
is not an installation. Promote those components after compatibility and recovery
exercises, with no second owner installing MetalLB or kube-vip Services.

## Sources

- [Terraform module composition](https://developer.hashicorp.com/terraform/language/modules/develop/composition)
- [Kubespray v2.32.0 release](https://github.com/kubernetes-sigs/kubespray/releases/tag/v2.32.0)
- [Pinned etcd deployment modes](https://github.com/kubernetes-sigs/kubespray/blob/v2.32.0/docs/operations/etcd.md)
- [Pinned kube-vip integration](https://github.com/kubernetes-sigs/kubespray/blob/v2.32.0/docs/ingress/kube-vip.md)
- [Proxmox VM provider schema](https://github.com/bpg/terraform-provider-proxmox/blob/v0.118.0/docs/resources/virtual_environment_vm.md)
