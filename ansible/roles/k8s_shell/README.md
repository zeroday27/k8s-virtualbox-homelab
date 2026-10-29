# Kubernetes Bash profile

`playbooks/04-k8s-shell.yml` manages a bounded block in the target user's
`~/.bash_aliases` and ensures `~/.bashrc` loads it. Other alias content is retained.
The role exports `KUBECONFIG` to the target user’s `~/.kube/config` by default,
installs Bash completion support, and generates kubectl Bash completion at
shell startup, and enables completion for `k`. It targets the control plane only
and can run after cluster bootstrap. It does not change kubeconfigs, login shells,
workers or Kubernetes resources.

`k8s_shell_user` defaults to `ansible_user`. `k8s_shell_kubeconfig` is the
configurable absolute user kubeconfig path; it must already be readable by that
user. The role checks readability without sudo, but does not copy credentials or
change kubeconfig permissions. `k8s_shell_aliases` contains the
editable alias mapping. The account must already exist, be non-root and use Bash.
Profile symlinks are rejected. Bash syntax is validated before profile writes.

From `ansible/`:

```sh
../.venv/bin/ansible-playbook playbooks/04-k8s-shell.yml --check --diff
../.venv/bin/ansible-playbook playbooks/04-k8s-shell.yml
```

Reconnect or run `source ~/.bashrc` in an existing Bash session. Aliases require
a working user kubeconfig and do not grant Kubernetes permissions themselves.
`kga` retains the current namespace; use `kga -A` for all namespaces. `all` still
covers a resource subset. Completion for the plain `k` alias is configured;
multi-word aliases retain their normal command behavior.
