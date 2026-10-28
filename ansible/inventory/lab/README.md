# Three-node ARM64 lab inventory

The repository-root `ansible.cfg` selects `hosts.yml` by default. It contains
one control-plane host and two workers, all in `lab_nodes`:

| Group | SSH alias / guest hostname |
| --- | --- |
| `control_plane` | `k8s-control-plane-01` |
| `workers` | `k8s-worker-01`, `k8s-worker-02` |

Run commands from the repository root using its validation virtualenv. SSH uses
`~/.ssh/k8s-vm-lab.pem` and the controller's existing SSH aliases. Each alias must
specify its actual address, user and trusted host-key file. Keep that controller
configuration, private keys and real network details outside public Git.
Do not disable host-key checking. Another controller needs its own trusted SSH
configuration before connecting; the inventory does not create SSH aliases.

Inspect inventory without starting or connecting to any VM:

```sh
.venv/bin/ansible-inventory --graph
.venv/bin/ansible lab_nodes --list-hosts
.venv/bin/ansible-playbook ansible/preflight.yml --syntax-check
```

After starting the required lab VMs, verify access and the guest contract:

```sh
.venv/bin/ansible lab_nodes -m ansible.builtin.ping
.venv/bin/ansible-playbook ansible/preflight.yml
```

Use `--limit control_plane`, `--limit workers` or a specific host name for
subsequent tasks. Preflight is read-only. OS baseline access gates still apply.
This is a guest-management inventory; Kubernetes deployment still requires the
release-gated specification/observation workflow and its separate pinned runner.
The internal `ansible/ansible.cfg` remains for the existing static-check workflow;
normal commands from the repo root use the root config above.
