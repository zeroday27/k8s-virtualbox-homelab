#!/usr/bin/env python3
"""Seal a marked, unjoined ARM64 lab image from inside its guest. Then power off."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import subprocess


def bootstrap_state(status, admin_user, installer_disabled):
    stages = ['init-local', 'init', 'modules-config', 'modules-final']
    if status.get('errors') or any(status.get(stage, {}).get('errors') for stage in stages):
        raise ValueError('cloud-init bootstrap has errors')
    warnings = [text for values in status.get('recoverable_errors', {}).values() for text in values]
    if status.get('status') == 'done' and not warnings:
        return 'done'
    known_warning = 'Not unlocking blank password for existing user ' + admin_user + '.'
    if (status.get('status') == 'disabled' and installer_disabled
            and status.get('modules-final', {}).get('finished', 0) > 0
            and all(text.startswith(known_warning) and 'no existing password set' in text for text in warnings)):
        return 'installer-disabled-after-completed-bootstrap'
    raise ValueError('cloud-init has an unreviewed warning or incomplete/disabled bootstrap')


def install_network_identity(root=Path('/')):
    """Name the fixed VirtualBox virtio slots before interfaces become active."""
    directory = root / 'etc/systemd/network'
    directory.mkdir(parents=True, exist_ok=True)
    for slot, name in [('08', 'nat0'), ('09', 'lab0')]:
        (directory / ('10-homelab-' + name + '.link')).write_text(
            '[Match]\nPath=pci-0000:00:' + slot + '.0*\nDriver=virtio_net\n'
            '\n[Link]\nName=' + name + '\nMACAddressPolicy=none\n')


def generalize(build_id, admin_user):
    if os.geteuid() != 0 or platform.machine() != 'aarch64':
        raise ValueError('Run as root inside the disposable ARM64 image-build guest')
    marker = json.loads(Path('/etc/homelab-image-build.json').read_text())
    if marker.get('build_id') != build_id or marker.get('purpose') != 'role-neutral-lab-template':
        raise ValueError('Build identity/purpose mismatch; refusing to generalize this host')
    user = pwd.getpwnam(admin_user)
    if user.pw_uid == 0:
        raise ValueError('Bootstrap administrator must not be root')
    for path in ['/etc/kubernetes', '/var/lib/etcd', '/var/lib/kubelet']:
        if Path(path).exists():
            raise ValueError('Cluster state exists; never seal a joined node')
    status_result = subprocess.run(['cloud-init', 'status', '--wait', '--format', 'json'], capture_output=True, text=True)
    if status_result.returncode not in [0, 2]:
        raise ValueError('cloud-init status command failed')
    disabled_file = Path('/etc/cloud/cloud-init.disabled')
    installer_disabled = disabled_file.exists() and disabled_file.read_text().startswith('Disabled by Ubuntu live installer after first boot.')
    bootstrap = bootstrap_state(json.loads(status_result.stdout), admin_user, installer_disabled)
    fstab = Path('/etc/fstab').read_bytes()
    subprocess.run(['apt-get', 'clean'], check=True)
    subprocess.run(['cloud-init', 'clean', '--logs', '--machine-id', '--seed', '--configs', 'all'], check=True)
    # The original OS installer owns root mounts; preserve them during cleanup.
    Path('/etc/fstab').write_bytes(fstab)
    for path in Path('/etc/netplan').glob('*.yaml'):
        path.unlink()
    for name in ['99-installer.cfg', '90-installer-network.cfg', 'subiquity-disable-cloudinit-networking.cfg', '00-subiquity-disable-cloudinit-networking.cfg']:
        (Path('/etc/cloud/cloud.cfg.d') / name).unlink(missing_ok=True)
    Path('/etc/cloud/cloud-init.disabled').unlink(missing_ok=True)
    for path in Path('/etc/ssh').glob('ssh_host_*_key*'):
        path.unlink()
    for home in [Path(user.pw_dir), Path('/root')]:
        (home / '.ssh/authorized_keys').unlink(missing_ok=True)
        (home / '.bash_history').unlink(missing_ok=True)
    for path in ['/var/log/installer', '/var/log/journal']:
        if Path(path).is_dir():
            shutil.rmtree(path)
    for directory in ['/var/lib/dhcp', '/var/lib/systemd/network']:
        if Path(directory).is_dir():
            for path in Path(directory).glob('*lease*'):
                if path.is_file():
                    path.unlink()
    subprocess.run(['systemctl', 'stop', 'systemd-random-seed.service'], check=True)
    Path('/var/lib/systemd/random-seed').unlink(missing_ok=True)
    dbus_id = Path('/var/lib/dbus/machine-id')
    dbus_id.unlink(missing_ok=True)
    dbus_id.parent.mkdir(parents=True, exist_ok=True)
    dbus_id.symlink_to('/etc/machine-id')
    install_network_identity()
    subprocess.run(['update-initramfs', '-u', '-k', 'all'], check=True)
    machine_id = Path('/etc/machine-id').read_text().strip()
    if machine_id not in ['', 'uninitialized']:
        raise ValueError('cloud-init did not reset machine-id')
    if list(Path('/etc/ssh').glob('ssh_host_*_key*')) or list(Path('/etc/netplan').glob('*.yaml')):
        raise ValueError('Guest identity or network state remains')
    if Path('/var/lib/cloud/seed').exists() and any(Path('/var/lib/cloud/seed').iterdir()):
        raise ValueError('Bootstrap seed remains')
    if (Path(user.pw_dir) / '.ssh/authorized_keys').exists():
        raise ValueError('Bootstrap authorized key remains')
    receipt = {'build_id': build_id, 'bootstrap_state': bootstrap, 'machine_id_reset': True, 'host_keys_removed': True,
               'bootstrap_key_removed': True, 'seed_removed': True, 'network_removed': True,
               'dbus_machine_id_linked': True, 'random_seed_removed': True,
               'early_network_identity_installed': True,
               'fstab_sha256': hashlib.sha256(fstab).hexdigest(),
               'qualification': 'generalized lab candidate; clone proof still required'}
    print(json.dumps(receipt, indent=2), flush=True)
    os.sync()
    subprocess.run(['systemctl', 'poweroff'], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-id', required=True, help='Must match the image-build marker')
    parser.add_argument('--admin-user', default='ubuntu')
    args = parser.parse_args()
    generalize(args.build_id, args.admin_user)


if __name__ == '__main__':
    main()
