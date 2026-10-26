#!/usr/bin/env python3
"""Read-only host checks with bounded subprocesses; never prints host identifiers."""
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path


def run(args):
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=8)
        if result.returncode:
            return {"status": "failed", "exit_code": result.returncode}
        return {"status": "ok", "output": result.stdout.strip()}
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "note": "Retry from an ordinary local terminal."}
    except OSError as exc:
        return {"status": "unavailable", "error": type(exc).__name__}


def main():
    root = Path(os.environ.get("LAB_VM_ROOT", str(Path.home() / "VirtualBox VMs" / "k8s-ha")))
    existing = root
    while not existing.exists():
        existing = existing.parent
    free_gib = round(shutil.disk_usage(existing).free / 1024**3, 1)
    report = {
        "architecture": platform.machine(),
        "host_os": platform.platform(),
        "vm_root": str(root),
        "free_gib": free_gib,
        "full_lab_storage_gate": "pass" if free_gib >= 100 else "needs_capacity",
        "note": "100 GiB minimum free-space planning gate; no files or VMs are changed.",
        "tools": {},
    }
    for name, args in {
        "virtualbox": ["VBoxManage", "--version"],
        "terraform": ["terraform", "version", "-json"],
        "virtualbox_inventory": ["VBoxManage", "list", "vms"],
        "virtualbox_networks": ["VBoxManage", "list", "hostonlynets"],
        "routes": ["netstat", "-rn", "-f", "inet"],
    }.items():
        report["tools"][name] = run(args)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
