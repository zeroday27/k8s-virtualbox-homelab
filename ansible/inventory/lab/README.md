# Three-node ARM64 lab inventory

The single `ansible/ansible.cfg` selects `inventory/lab/hosts.yml` by default.
It contains one control-plane host and two workers, all in `lab_nodes`:

| Group | SSH alias / guest hostname |
| --- | --- |
| `control_plane` | `k8s-control-plane-01` |
| `workers` | `k8s-worker-01`, `k8s-worker-02` |

Run commands from the `ansible/` directory using the repository validation
virtualenv. From the repository root, first run `cd ansible`. SSH uses
`~/.ssh/k8s-vm-lab.pem` and the controller's existing SSH aliases. Each alias must
specify its actual address, user and trusted host-key file. Keep that controller
configuration, private keys and real network details outside public Git.
Do not disable host-key checking. Another controller needs its own trusted SSH
configuration before connecting; the inventory does not create SSH aliases.

Inspect inventory without starting or connecting to any VM:

```sh
../.venv/bin/ansible-inventory --graph
../.venv/bin/ansible lab_nodes --list-hosts
../.venv/bin/ansible-playbook preflight.yml --syntax-check
```

After starting the required lab VMs, verify access and the guest contract:

```sh
../.venv/bin/ansible lab_nodes -m ansible.builtin.ping
../.venv/bin/ansible-playbook preflight.yml
```

Use `--limit control_plane`, `--limit workers` or a specific host name for
subsequent tasks. Preflight is read-only. OS baseline access gates still apply.
This is a guest-management inventory; Kubernetes deployment still requires the
release-gated specification/observation workflow and its separate pinned runner.
There is no duplicate configuration at the repository root. To run from another
directory, explicitly select this config, for example from the repository root:

```sh
ANSIBLE_CONFIG=ansible/ansible.cfg .venv/bin/ansible-inventory --graph
```

Inventory and role paths resolve relative to `ansible/ansible.cfg`. Existing Make
and CI checks use this same configuration.
