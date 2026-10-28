# Reviewed Ubuntu OS baseline

Run from `ansible/`; `playbooks/os-baseline.yml` applies this role serially, one
inventory host at a time. Ansible already iterates over hosts: `baseline_hostname`
defaults to each `inventory_hostname`. Override it in `host_vars` if needed.
The lab defaults select Asia/Bangkok and a restricted IPv4 host-input firewall.
The reusable role leaves the firewall disabled until a site selects its peers.

| Concern | Variables / behavior |
| --- | --- |
| Packages | apt metadata refresh precedes installation; cache TTL `baseline_apt_cache_valid_time: 3600`; no distribution upgrade |
| Identity/time | `baseline_hostname`, `baseline_timezone: Asia/Bangkok`, `baseline_ntp_servers: [ntp.ubuntu.com]`; chrony |
| Swap | `baseline_swap_disabled: true`; comment fstab entries, mask discovered swap units, swapoff on apply; retain swap files |
| AppArmor | `baseline_apparmor_required: true`; require enabled kernel support, inspect profiles, enable service; workload/containerd profiles belong to Kubernetes integration |
| SSH | trusted key and sudo access plus recovery console required; key-only login, root login disabled; validate effective configuration before reload and reconnect |
| Logs | journal 256M/14day; global logrotate daily, 14 rotations, maxsize 50M, compression; retain package-specific rules; audit logs 5 x 16MB |
| Kernel | ASLR, restricted kernel pointers/dmesg, protected links, disabled redirects/source routing, SYN cookies; preserve forwarding, IPv6 and CNI networking |
| Storage | `baseline_lvm_enabled: false`; optional dedicated extra disks, explicit stable by-id paths and absolute LV sizes; never convert the existing root disk |

## Private site variables

Install pinned collections with `ansible-galaxy collection install -r requirements.yml`.
Create ignored `inventory/lab/group_vars/lab_nodes/90-site.local.yml` with actual
allowlists. The following addresses are documentation examples only:

```yaml
baseline_bastion_cidrs: [192.0.2.1/32]
baseline_node_addresses: [192.0.2.11, 192.0.2.21, 192.0.2.22]
baseline_control_plane_addresses: [192.0.2.11]
baseline_pod_cidrs: [10.244.0.0/16]
baseline_cni_transport: ipip
# Set true only after verifying trusted SSH, noninteractive sudo and recovery.
baseline_access_verified: false
```

The role compares the actual SSH source with the bastion allowlist and rejects
broad node/bastion CIDRs. It refuses active UFW/firewalld or a separately active
nftables service; migrate those deliberately. It never disables a foreign manager
or flushes the global ruleset. This implementation supports an IPv4 cluster.

| Inbound destination | Allowed sources |
| --- | --- |
| SSH TCP22 on every node | Individual bastion addresses only |
| API TCP6443 on control planes | Nodes, bastions, configured pod CIDRs |
| etcd TCP2379/2380 on control planes | Control planes only |
| kubelet TCP10250 on every node | Control planes; pod CIDRs only when `baseline_metrics_to_kubelet: true` |
| Calico IPIP protocol4 + BGP TCP179 | Nodes only, with `baseline_cni_transport: ipip` |
| Calico VXLAN UDP4789 | Nodes only, with `baseline_cni_transport: vxlan` |
| Calico unencapsulated BGP TCP179 | Nodes only, with `baseline_cni_transport: none` |
| NodePort TCP/UDP30000–32767 on workers | Disabled; requires `baseline_nodeport_enabled` and explicit `baseline_nodeport_sources` |

Loopback, established/related traffic, NAT-interface DHCP renewal, essential ICMP
errors, required IPv6 error/neighbor/router messages and bastion/node IPv4 ping
are also allowed. Unrestricted IPv6 ICMP and IPv6 echo are not accepted. No application
listeners are open over IPv6. Scheduler/controller-manager10259/10257 remain local;
kube-proxy health10256 is not exposed to external load balancers in this profile.
The DHCP interface defaults to the image's `nat0`; adjust the template if using a
different image contract. Typha, WireGuard, additional CNI modes and external etcd
need a separate reviewed policy before enabling them.

The dedicated nftables table owns **host input only**, with no forwarding/output
or NAT hooks. Calico/kube-proxy retain those tables. Both firewall systems must
accept required traffic: an accept in one base chain cannot bypass a later drop.
Match the transport to the rendered Kubernetes configuration before installation.
Calico recommends its host endpoint policies over competing host firewall managers;
this bounded input policy still needs a live CNI/pod traffic canary before cluster
qualification. A check-mode success does not demonstrate that compatibility.

On apply, native `nft --check` validates syntax, and a 120-second rollback timer
protects activation until a fresh SSH connection succeeds. Recovery restores this
role's previous runtime table, persistent rules and service enablement. Review
console recovery first; neither the rollback path nor traffic isolation is proven
by a dry run. No apply or automatic reboot is performed by validation commands.

## Optional LVM

Use a new, dedicated extra data disk; the current root layout remains unchanged.
Declare `baseline_lvm_devices: [/dev/disk/by-id/...]`, `baseline_lvm_vg` and
`baseline_lvm_volumes`, each with `name`, absolute `size` such as `8g`, `mount` under
`/srv/`, `fstype` (`ext4` or `xfs`) and `opts: defaults,nodev,nosuid`.
Preflight checks root-disk ancestry, partitions, wipefs signatures, existing PV/VG
ownership and occupied mount directories. Existing volumes may grow, never shrink;
no forced formatting or removal of other PVs. Size availability is ultimately
checked by LVM on apply. Check mode validates device safety and prints the plan;
it does not provision VG/LV/filesystems or mounts. Storage requires separate
extra-disk apply/reboot qualification. Root LVM must be designed in a future image
build; this role does not migrate an installed root filesystem.

## Verification

```sh
../.venv/bin/ansible-playbook playbooks/os-baseline.yml --syntax-check
ansible-lint --offline -c .ansible-lint.yml playbooks/os-baseline.yml roles/os_baseline
../.venv/bin/ansible-playbook playbooks/os-baseline.yml --check --diff --limit control_plane
../.venv/bin/ansible-playbook playbooks/os-baseline.yml --check --diff
```

Keep `baseline_access_verified` false until access/recovery are verified, even for
check mode. Check mode predicts package/configuration changes and runs read-only
queries plus native nft, SSH-directive and logrotate syntax validation. It skips SSH reload, swapoff, firewall
activation/rollback, sysctl application, handler restarts and storage provisioning.
Absent-package audit configuration and services await an apply. Native validation runs separately using rendered content over stdin without
activating it. SSH snippet syntax is checked in dry run; full effective SSH policy
with existing includes is validated only on apply before reload.
Ansible may create temporary module files; guest boot/log activity is expected.

## References and deliberate limits

[Platform9's OS-hardening guide](https://platform9.com/blog/hardening-the-os-in-kubernetes-clusters-is-a-critical-security-requirement/)
is a useful checklist for SSH, auditing, AppArmor, time, patching and log retention.
Its 2021 Ubuntu20.04 benchmark examples are not a ready-made policy for this lab.
We select conservative controls, keep Kubernetes networking functional and avoid
benchmark-wide remediation, unnecessary services, forced disk changes and reboots.
This is not a CIS certification or a full audit-rules/patch orchestration solution.

Port scopes follow the [Kubernetes port reference](https://kubernetes.io/docs/reference/networking/ports-and-protocols/)
and [Calico requirements](https://docs.tigera.io/calico/latest/getting-started/kubernetes/requirements).
See [nftables chain behavior](https://wiki.iptables.org/wiki-nftables/index.php/Configuring_chains)
for interactions between independent base chains.
