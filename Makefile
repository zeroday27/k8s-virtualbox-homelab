PYTHON ?= .venv/bin/python
TERRAFORM ?= terraform
ANSIBLE_PLAYBOOK ?= .venv/bin/ansible-playbook
SPEC ?= specs/lab-virtualbox-single.json
OUT ?= .generated/review

.PHONY: init check check-python check-terraform check-ansible plan preview

# Downloads/initializes tools only; no hypervisor calls or apply.
init:
	$(TERRAFORM) -chdir=terraform init -backend=false
	$(TERRAFORM) -chdir=terraform/adapters/proxmox init -backend=false -lockfile=readonly

check: check-python check-terraform check-ansible

check-python:
	$(PYTHON) scripts/check_public.py
	$(PYTHON) scripts/specctl.py validate --spec specs/lab-virtualbox-single.json
	$(PYTHON) scripts/specctl.py validate --spec specs/lab-virtualbox.json
	$(PYTHON) scripts/specctl.py validate --spec specs/production-proxmox.example.json
	$(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) -m py_compile scripts/specctl.py scripts/preflight.py scripts/check_public.py
	bash -n scripts/fetch-kubespray.sh

check-terraform:
	$(TERRAFORM) fmt -check -recursive terraform
	$(TERRAFORM) -chdir=terraform validate
	$(TERRAFORM) -chdir=terraform test -no-color
	$(TERRAFORM) -chdir=terraform/adapters/proxmox validate

check-ansible:
	ANSIBLE_CONFIG="$(CURDIR)/ansible/ansible.cfg" ANSIBLE_LOCAL_TEMP="$(CURDIR)/.generated/ansible-tmp" $(ANSIBLE_PLAYBOOK) -i 'localhost,' --syntax-check ansible/preflight.yml
	ANSIBLE_CONFIG="$(CURDIR)/ansible/ansible.cfg" ANSIBLE_LOCAL_TEMP="$(CURDIR)/.generated/ansible-tmp" $(ANSIBLE_PLAYBOOK) -i 'localhost,' --syntax-check ansible/playbooks/os-baseline.yml

# Planning root only; this target never selects a provisioning adapter.
plan:
	$(PYTHON) scripts/specctl.py validate --spec "$(SPEC)"
	$(TERRAFORM) -chdir=terraform plan -var='spec_file=$(abspath $(SPEC))'

preview:
	$(PYTHON) scripts/specctl.py render --spec "$(SPEC)" --output "$(OUT)"
