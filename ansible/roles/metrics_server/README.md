# Metrics Server add-on

`05-k8s-components.yml` is a shared add-on entry point. Every component has its
own role, variables, version lock and tag. Initially it selects `metrics_server`;
later roles can be added without modifying bootstrap or Calico installation.

## Version and ownership

`ansible/vars/k8s-components.bom.json` pins Metrics Server v0.9.0, its upstream
components manifest SHA256, OCI image index and verified ARM64/AMD64 child
manifests. Upstream supports Kubernetes 1.34+. The role supports the current
Ubuntu 26.04 lab topology and uses the Kubernetes API for architecture discovery.
Runtime qualification is separate for each architecture. This installation BOM
is not a transitive package/license SBOM. A tagged selection has been prepared;
installation and Metrics API readiness require the explicit apply below.

The single-control-plane lab spec selects Metrics Server. In the Ansible
inventory `10-components.yml` selects it and derives
`baseline_metrics_to_kubelet` from the same flag. The baseline still owns its
nftables input table, timed rollback, SSH sources and persistence. Phase 05 calls
only baseline validation/firewall tasks; it does not rerun the whole OS baseline.

## TLS and network prerequisites

The three plays validate the cluster, prepare nodes serially, then install the
add-on on the control plane. The node phase enables `serverTLSBootstrap` while
preserving the remaining kubelet settings, restarts kubelet on one node at a
time, and requests a cluster-signed serving certificate. Explicit custom kubelet
certificate/key paths are rejected rather than replaced. Existing workloads are
not drained or recreated by this role. Native TLS verification checks the chain
and each node's observed management IP before advancing.

Only pending `kubernetes.io/kubelet-serving` CSRs for this inventory node may be
approved. The controller validates CSR signature, authenticated node username
and groups, exact CN/organization, server-only usages, key strength and exact
hostname/IP SANs. Foreign addresses, alternate identities, extra extensions,
issued/denied requests and unexpected names are rejected. Approval PUTs carry
the reviewed UID/resourceVersion to prevent approving a replaced request. There
is no blanket CSR approver or background approval controller.

The baseline allows configured pod CIDRs and exact inventory node IPs to kubelet
TCP10250 when metrics are enabled. Node sources cover Calico outgoing source NAT
and rescheduling of the scraper. No management subnet or public CIDR is allowed; kubelet
webhook authentication/authorization remains required. Existing control-plane
sources remain allowed. Forward/output/NAT rules remain owned by Calico and
kube-proxy. No bastion SSH sources or public port access are added.

The control plane generates a separate 365-day Metrics Server serving certificate
with service DNS SANs, signed locally using the existing cluster CA. Its key
stays root-only in private state and a Kubernetes TLS Secret. CA keys are never
copied to the controller, workers, public manifests or Git. Secret operations
use stdin and server-side apply without last-applied annotations. The helper
emits only change flags and the public certificate fingerprint.
External-CA clusters require a separately reviewed signer workflow.

Metrics Server verifies kubelet certificates against the cluster CA and selects
InternalIP. APIService verifies the Metrics Server certificate with caBundle;
`insecureSkipTLSVerify` is false. The role adds no `--kubelet-insecure-tls` flag.
The 0440 Secret volume uses fsGroup 1000 for the upstream non-root container.

The central kubeadm `kubelet-config` ConfigMap is updated to retain serving TLS
across later node upgrades. Component ownership markers prevent silent adoption
of an existing Deployment, TLS Secret or APIService.

## Variables and commands

| Variable | Default |
| --- | --- |
| `k8s_components_metrics_server_enabled` | true in the selected lab inventory |
| `metrics_server_replicas` | 1, deliberate lab profile |
| `metrics_server_cpu_request` | 100m |
| `metrics_server_memory_request` | 200Mi |
| `metrics_server_certificate_days` | 365 |
| `metrics_server_renew_before_days` | 30 |
| `metrics_server_timeout` | 300s |

From `ansible/`, with all three nodes reachable:

```sh
../.venv/bin/ansible-playbook playbooks/05-k8s-components.yml \
  --tags metrics_server --check --diff -e '{"baseline_access_verified":true}'
../.venv/bin/ansible-playbook playbooks/05-k8s-components.yml \
  --tags metrics_server -e '{"baseline_access_verified":true}'
```

Do not limit the inventory: kubelet certificates and scraping access are needed
on every node. Check mode reads nodes/configuration and validates nft syntax,
predicts kubelet/firewall files and previews the overlay. It does not restart
kubelet, request/approve CSRs, issue certificates, publish Secrets, build remotely
or apply API resources. It cannot establish runtime metrics readiness.

After apply the role waits for rollout and APIService availability, then requires
resource metrics for all inventory nodes and runs `kubectl top nodes` and
`kubectl top pods -A`. CPU/memory metrics support top and autoscaling, not a
historical monitoring stack or an HPA policy by themselves.

On the control plane the public overlay is under `/opt/k8s-components/metrics-server`.
Private state/certificates are under `/var/lib/k8s-components/metrics-server`.
The role installs `metrics-server-renew.timer` on the control plane. It checks at
03:00 Asia/Bangkok daily, with up to 15 minutes of randomized delay. `Persistent=true`
catches a missed calendar run after the VM starts again. The control-plane VM and
Kubernetes API must be running; the administrator's computer need not be connected.

The root-only service keeps the cluster CA key on the control plane, issues a
365-day leaf when fewer than 30 days remain, reconciles only the owned TLS Secret,
and changes the Deployment's certificate fingerprint to roll out the new leaf.
It verifies rollout and API availability. Healthy checks perform no Secret or
Deployment writes. A shared file lock serializes timer and Ansible certificate
operations. Failed checks are visible in systemd/journal and retry after 15 minutes;
there is no external alert delivery. Secret data is passed through stdin and never
written to the journal. The service has a read-only system filesystem except for
its private state directory. It uses the existing local administrator kubeconfig;
this lab mechanism is not a least-privilege external certificate platform.

Changing the lifetime from 90 to 365 days reissues the existing leaf on the next
apply. The signer must remain valid longer than the requested leaf lifetime.
The service also repairs interrupted publication or a mismatched Secret on retry.

Inspect or run the automation on the control plane:

```sh
sudo systemctl list-timers metrics-server-renew.timer
sudo systemctl start metrics-server-renew.service
sudo journalctl -u metrics-server-renew.service -n 20 --no-pager
sudo openssl x509 -in /var/lib/k8s-components/metrics-server/tls/tls.crt -noout -dates
```

The automatic service renews only the Metrics Server serving leaf. It does not
rotate the cluster CA, administrator kubeconfig, API server certificates or approve
kubelet CSRs. Rerunning the role still processes validated pending kubelet serving
renewal requests. Kubelet serving CSRs are not auto-approved by kube-controller-manager.
The timer remains installed until explicitly disabled; changing the component flag
alone does not stop existing automation. Disabling the flag does not uninstall the add-on or undo
serving TLS; removal and trust migration need an explicit reviewed workflow.

Sources: [Metrics Server requirements](https://github.com/kubernetes-sigs/metrics-server#requirements),
[kubeadm certificate management](https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-certs/),
[CSR API](https://kubernetes.io/docs/reference/access-authn-authz/certificate-signing-requests/).

Timer reference: [systemd.timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html).
