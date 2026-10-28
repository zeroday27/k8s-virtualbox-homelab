# Security, operations and recovery acceptance

## Release meaning

`candidate` means examples and static validation exist. `qualified` requires
recorded evidence for the exact image, architecture, hypervisor/provider, runner,
Kubernetes/CNI versions and add-on digests. A profile named production does not
certify that evidence. Keep measurements, real addresses, credentials and reports
private; publish generic contracts and reusable procedures.

A production release is accepted only when all relevant gates pass:

| Gate | Required evidence |
| --- | --- |
| Identity and management | Trusted SSH identities, key-only non-root access, tested sudo and console recovery, OIDC/RBAC and audited break-glass access |
| Image supply chain | Signed source checksum verification, immutable build manifest, artifact provenance, SBOM/scans and unique clone identity |
| Placement and capacity | Three independent control-plane failure domains, worker spread, measured etcd disk latency, headroom and storage/network redundancy |
| Network | Reserved non-overlapping networks, DNS/NTP, MTU, expected interface routes, API access policy, CNI-aware firewall rules and NetworkPolicy tests |
| Host security | AppArmor active, reviewed patch policy, services/accounts audit, no credential leaks, security baseline canary and repeat-run evidence |
| Kubernetes security | Current supported patch bundle, restricted API/etcd access, kubelet authentication/authorization, encryption of stored Secrets, API audit, OIDC/RBAC and admission-policy tests |
| Components | Healthy DNS/CNI, API VIP and application LB failover, certificate issuance/renewal, CSI attach/detach and backup/restore, external alert delivery |
| Operations | Clean Terraform refresh/plan, idempotent Ansible, tested node replacement, one-minor-at-a-time upgrade strategy, certificate-expiry monitoring and signed change records |
| Recovery | Independent backups and credentials, isolated restore, data consistency validation, measured workload-specific RPO/RTO and tested failback |

The current code implements specification validation, observations-to-inventory,
a provider scaffold and a limited baseline role. It does not implement every gate
above. Use an appropriate benchmark version (for example CIS) as an assessment
input, maintain exceptions, and test remediation against the selected runtime.
Never claim compliance from a scanner exit code alone.

## Management and network policy

Keep API, SSH, Proxmox management and etcd private, reachable through an approved
management network/VPN/bastion. Limit SSH source CIDRs; separate human access and
short-lived automation identities. Keep the API server on an HA endpoint covered
by its certificate SANs. Restrict etcd peer/client access to the required control
planes and administrative recovery identities.

Derive the firewall matrix from the selected versions and topology. At minimum
review API TCP 6443, etcd TCP 2379–2380, kubelet TCP 10250, DNS, selected CNI
transport, MetalLB TCP/UDP 7946, management SSH and required outbound repositories.
Flannel VXLAN and Calico/Cilium choices have different requirements. BGP adds
its own peer restrictions. NodePort and metrics exposure are explicit decisions,
not public defaults. Test both desired connectivity and denied paths.

Workload namespaces default to restricted Pod Security where feasible. System,
CNI, CSI, monitoring and networking components may need documented exceptions;
use narrowly scoped service accounts and namespaces, not global relaxation.
Require NetworkPolicy tests, image provenance/scanning, resource requests/limits,
readiness probes and suitable disruption budgets for production workloads.

Use reviewed OS patch windows and rolling reboots, honoring drain constraints.
Hold/pin Kubernetes packages and upgrade through the selected engine. Automatic
host updates must not silently replace Kubernetes/runtime components or reboot
all control planes. No role should disable AppArmor, swap policy or TLS validation
to hide a compatibility failure.

## Backup domains and ownership

Protect these separately; none is a substitute for the others:

| Domain | Contents | Restore dependency |
| --- | --- | --- |
| Infrastructure | Private spec, Terraform state/version history, provider locks, image build manifests, hypervisor configuration | Backend/object store and image artifacts accessible without Kubernetes |
| Cluster control plane | etcd snapshots, Kubernetes/etcd PKI, service-account keys, Secrets encryption/KMS recovery material, selected engine version | Correct etcd tooling, decryption keys and documented membership reset |
| Platform configuration | GitOps repositories, reconciler bootstrap, chart/image digests and secret references | Git/registry/identity/secret services independently reachable |
| Workload data | Database-native consistent backups/PITR, application exports and CSI/PV backups where supported | Application ordering and consistency validation |
| External dependencies | DNS, identity, certificates, storage, registry, backup credentials and KMS/secret stores | Independently recoverable access paths and owners |

Encrypt backup content; protect keys separately. Keep immutable/off-site copies
under identities that the cluster cannot erase. Verify retention and restore
access, not just upload success. Restore testing must include expiry/rotation
of backup credentials and decryption material. A VM snapshot is not an
application-consistent backup; an etcd snapshot contains cluster metadata and
Secrets, not the contents of all PVs or external databases.

The production example contains illustrative RPO/RTO values, not a business SLA.
Set objectives per workload after estimating restore throughput and dependencies.
A 15-minute etcd schedule does not imply 15-minute database RPO. Backup age,
last successful restore, consistency checks and alert routing must be observable.

## Recovery patterns

1. **Healthy cluster, lost node:** preserve quorum; replace one node at a time
   using the engine's membership procedure, then verify the new node and workload
   rescheduling. Never clone joined etcd membership or reuse a stale node disk.
2. **Cluster healthy, workload loss:** use application-native recovery/PITR or
   qualified volume recovery; validate business data before returning traffic.
3. **Control-plane quorum loss:** fence the failed cluster, preserve forensic
   copies, validate a known-good snapshot and restore new membership in an
   isolated environment using the exact supported etcd tool/version. Follow etcd's
   Kubernetes-specific revision-bump/mark-compacted guidance where applicable.
   Do not join restored members to a live divergent cluster.
4. **Site loss:** provision fresh site infrastructure from the private DR spec,
   recover secret/identity/network prerequisites, restore the selected cluster
   and application data, validate service behavior, then perform a controlled
   DNS/LB cutover. Old-site fencing prevents two writable copies of the same data.

A rebuild from GitOps restores desired configuration; it does not replace stateful
data recovery. Full-cluster etcd restore and fresh-cluster/GitOps recovery are
distinct runbooks. Qualify both if both are offered; preserve CA/encryption keys
and account for endpoint, certificate, storage and identity changes.

Cross-hypervisor DR means rebuild on another adapter and restore portable data.
It does not promise direct migration of a VM disk or snapshot. Cross-architecture
DR additionally needs compatible multi-architecture application images, supported
DB/plugin data formats and new platform qualification. Keep etcd members within
a supported low-latency failure domain; do not stretch quorum across an arbitrary
WAN as a substitute for a DR site.

## Restore drill and failback

Run at the declared interval and after material version/storage changes:

1. Declare scope and recovery owner; fence or isolate the restore target.
2. Recover private specs, state, image/runner artifacts and independent credentials.
3. Select a clean backup by age and integrity, and record the expected data point.
4. Provision isolated VMs; prove trusted access, placement and OS/runtime health.
5. Restore the chosen control-plane or fresh-cluster path, then storage and apps.
6. Verify identity, DNS, certificates, policies, data consistency and a business
   transaction. Record actual RPO/RTO and evidence, including failures.
7. Exercise traffic cutover and rollback. Keep one authoritative writer throughout.
8. Re-establish backup protection before normal service and plan failback explicitly.

No destructive restore automation is included yet. Build and test it against a
disposable cluster first. The production validator requires a private evidence
reference, but only an actual reviewed drill proves the objectives.

## Sources

- [Kubernetes security checklist](https://kubernetes.io/docs/concepts/security/security-checklist/)
- [Kubeadm high availability](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/high-availability/)
- [etcd disaster recovery](https://etcd.io/docs/v3.6/op-guide/recovery/)
- [Kubespray operations](https://github.com/kubernetes-sigs/kubespray/tree/v2.32.0/docs/operations)
