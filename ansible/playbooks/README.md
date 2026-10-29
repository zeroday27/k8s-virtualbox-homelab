# Lab playbook order

Run from the `ansible/` directory with the existing three-node inventory.
Numbers describe execution order. Roles retain descriptive names so they remain
reusable; each play selects its role or task phase explicitly.

| Order | Playbook | Role / phase | When to use |
| --- | --- | --- | --- |
| 00 | `00-os-base.yml` | `os_baseline` | Guest OS identity, security and networking baseline |
| 01 | `01-k8s-base.yml` | `k8s_base` | Runtime and tools before cluster membership |
| 02 | `02-k8s-bootstrap.yml` | `k8s_base` preflight, init and join | Initialize the control plane and join workers |
| 03 | `03-k8s-calico.yml` | `k8s_base` Calico phase | Apply the CNI and check rollouts and node readiness |
| 04 | `04-k8s-shell.yml` | `k8s_shell` | User KUBECONFIG, aliases and Bash completion on control plane |

`../preflight.yml` remains a separate read-only guest qualification check.
The numbered plays are explicit entry points, not an automatic full rerun.
The base install rejects joined nodes. Bootstrap and Calico require the full
inventory. Use the dedicated shell play for profile changes on an existing
cluster. Renaming playbooks does not require rerunning OS or cluster phases.

```sh
../.venv/bin/ansible-playbook playbooks/04-k8s-shell.yml --check --diff
../.venv/bin/ansible-playbook playbooks/04-k8s-shell.yml
```

The shell role expects an existing user-readable kubeconfig, normally
`~/.kube/config`. It exports that path and retains permissions and credentials.
Reconnect or run `source ~/.bashrc` after a profile update. Use `kubectl` directly
as the configured user; `sudo` can reset the environment and select root's config.
