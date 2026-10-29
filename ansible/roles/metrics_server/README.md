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

The control plane generates a separate 90-day Metrics Server serving certificate
with service DNS SANs, signed locally using the existing cluster CA. Its key
stays root-only in private state and a Kubernetes TLS Secret. CA keys are never
copied to the controller, workers, public manifests or Git. Secret operations
use stdin, no_log and server-side apply without last-applied annotations.
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
| `metrics_server_certificate_days` | 90 |
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
Rerun the same role before the serving leaf has fewer than 30 days remaining.
It also processes validated pending kubelet serving renewal requests. Kubelet
serving CSRs are not auto-approved by kube-controller-manager, so renewal needs
an explicit role run; no scheduler is installed. The leaf fingerprint triggers
rollout when renewed. Disabling the flag does not uninstall the add-on or undo
serving TLS; removal and trust migration need an explicit reviewed workflow.

Sources: [Metrics Server requirements](https://github.com/kubernetes-sigs/metrics-server#requirements),
[kubeadm certificate management](https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-certs/),
[CSR API](https://kubernetes.io/docs/reference/access-authn-authz/certificate-signing-requests/).
