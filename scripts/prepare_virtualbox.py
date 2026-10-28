#!/usr/bin/env python3
"""Prepare private Ubuntu ARM64 media and VM command plans. Never invoke VBoxManage."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

import yaml

from specctl import expanded_nodes, load_json, private_output, validate, write_private

SIGNING_FINGERPRINT = '843938DF228D22F7B3742BC0D94AA3F0EFE21092'


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(8 * 1024**2):
            value.update(chunk)
    return value.hexdigest()


def mac(namespace, node, nic):
    raw = hashlib.sha256(f'{namespace}:{node}:{nic}'.encode()).hexdigest()[:10]
    return '02:' + ':'.join(raw[n:n + 2] for n in range(0, 10, 2))


def seed_config(spec, node_name, namespace, public_key):
    node = expanded_nodes(spec)[node_name]
    prefix = ipaddress.ip_network(spec['network']['node_cidr']).prefixlen
    nat_mac = mac(namespace, node_name, 'nat')
    lab_mac = mac(namespace, node_name, 'lab')
    user = spec['security']['ssh_user']
    if node['interface'] == 'nat0':
        raise ValueError('Host-only interface cannot use the NAT interface name')
    sudo_command = (f"printf '%s\\n' '{user} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-lab-bootstrap; "
                    "chmod 0440 /etc/sudoers.d/90-lab-bootstrap; visudo -cf /etc/sudoers.d/90-lab-bootstrap")
    config = {'autoinstall': {
        'version': 1, 'refresh-installer': {'update': False}, 'locale': 'en_US.UTF-8',
        'keyboard': {'layout': 'us'}, 'timezone': 'Etc/UTC',
        'identity': {'hostname': node_name, 'username': user, 'password': '!'},
        'ssh': {'install-server': True, 'allow-pw': False, 'authorized-keys': [public_key]},
        'network': {'version': 2, 'renderer': 'networkd', 'ethernets': {
            'nat0': {'match': {'macaddress': nat_mac}, 'set-name': 'nat0',
                     'dhcp4': True, 'dhcp6': False, 'dhcp4-overrides': {'route-metric': 100},
                     'nameservers': {'addresses': spec['network']['dns_servers']}},
            node['interface']: {'match': {'macaddress': lab_mac}, 'set-name': node['interface'],
                                'dhcp4': False, 'dhcp6': False, 'link-local': [],
                                'addresses': [f"{node['ip']}/{prefix}"]}}},
        'storage': {'layout': {'name': 'direct', 'match': {'size': 'largest'}}, 'swap': {'size': 0}},
        'packages': ['python3', 'python3-apt', 'sudo', 'ca-certificates', 'chrony'],
        'updates': 'security',
        'late-commands': [['curtin', 'in-target', '--target=/target', '--', 'sh', '-ec', sudo_command]],
        'shutdown': 'poweroff'}}
    metadata = {'instance-id': f'{namespace}-{node_name}', 'local-hostname': node_name}
    if spec['profile'] == 'lab':
        # Small guests must not lose hundreds of MiB to an unused crash kernel.
        # Keep this policy out of production images and preserve other boot args.
        config['autoinstall']['kernel-crash-dumps'] = {'enabled': False}
        memory_policy = '# Lab-only memory policy; kernel crash dumps are disabled.\nGRUB_CMDLINE_LINUX_DEFAULT="$(printf \'%s\\n\' "$GRUB_CMDLINE_LINUX_DEFAULT" | sed -E \'s/(^|[[:space:]])crashkernel=[^[:space:]]+//g\')"\n'
        config['autoinstall']['late-commands'].extend([
            ['curtin', 'in-target', '--target=/target', '--', 'python3', '-c',
             "from pathlib import Path; Path('/etc/default/grub.d/zz-lab-memory.cfg').write_text(" + repr(memory_policy) + ")"],
            ['curtin', 'in-target', '--target=/target', '--', 'update-grub']])
    return config, metadata, nat_mac, lab_mac


def patch_grub(text):
    if 'autoinstall' in text:
        raise ValueError('Expected the original installer GRUB configuration')
    changed = 0
    lines = []
    for line in text.splitlines():
        if re.match(r'^\s*linux\s+/casper/vmlinuz(?:\s|$)', line):
            line = re.sub(r'\s+---', ' autoinstall ds=nocloud ---', line, count=1)
            if 'autoinstall ds=nocloud' not in line:
                raise ValueError('Unrecognized Ubuntu kernel command line')
            changed += 1
        line = re.sub(r'^(\s*set timeout=)\d+\s*$', r'\g<1>1', line)
        lines.append(line)
    if not changed:
        raise ValueError('No supported ARM64 Ubuntu boot entry found')
    return '\n'.join(lines) + '\n'


def update_md5(text, relative_name, contents):
    checksum = hashlib.md5(contents).hexdigest()
    rows = text.splitlines()
    found = False
    for index, line in enumerate(rows):
        parts = line.split(maxsplit=1)
        if len(parts) == 2 and parts[1].lstrip('*').removeprefix('./') == relative_name:
            rows[index] = checksum + '  ./' + relative_name
            found = True
    if not found:
        raise ValueError('Installer checksum manifest does not cover the patched GRUB file')
    return '\n'.join(rows) + '\n'


def run(command, timeout=300):
    result = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{command[0]} preparation failed: {result.stderr[-1800:]}')
    return result.stdout + result.stderr


def planned_commands(spec, name, node, namespace, runtime, installer, seed, network_name, nat_mac, lab_mac):
    vm_id = str(uuid.uuid5(namespace, name))
    disk = str(runtime / 'machines' / f'{spec["name"]}-{name}' / 'root.vdi')
    # The tested host's modifyvm option accepts the configured Name, not the
    # synthesized VBoxNetworkName shown alongside it by `list hostonlynets`.
    commands = [
        ['VBoxManage', 'createvm', '--name=' + spec['name'] + '-' + name,
         '--platform-architecture=arm', '--ostype=Ubuntu_arm64', '--uuid=' + vm_id,
         '--basefolder=' + str(runtime / 'machines'), '--register'],
        ['VBoxManage', 'modifyvm', vm_id, '--cpus=' + str(node['cpus']),
         '--memory=' + str(node['memory_mib']), '--firmware=efi', '--graphicscontroller=vmsvga',
         '--nic1=nat', '--nic-type1=virtio', '--mac-address1=' + nat_mac.replace(':', ''),
         '--nic2=hostonlynet', '--nic-type2=virtio', '--host-only-net2=' + network_name,
         '--mac-address2=' + lab_mac.replace(':', ''), '--boot1=dvd', '--boot2=disk'],
        ['VBoxManage', 'createmedium', 'disk', '--filename=' + disk,
         '--size=' + str(node['root_disk_gib'] * 1024), '--format=VDI', '--variant=Standard'],
        ['VBoxManage', 'storagectl', vm_id, '--name=SATA', '--add=sata', '--controller=IntelAhci', '--portcount=3'],
        ['VBoxManage', 'storageattach', vm_id, '--storagectl=SATA', '--port=0', '--device=0', '--type=hdd', '--medium=' + disk],
        ['VBoxManage', 'storageattach', vm_id, '--storagectl=SATA', '--port=1', '--device=0', '--type=dvddrive', '--medium=' + str(installer)],
        ['VBoxManage', 'storageattach', vm_id, '--storagectl=SATA', '--port=2', '--device=0', '--type=dvddrive', '--medium=' + str(seed)],
    ]
    return {'uuid': vm_id, 'name': spec['name'] + '-' + name, 'ip': node['ip'],
            'cpus': node['cpus'], 'memory_mib': node['memory_mib'], 'root_disk_gib': node['root_disk_gib'],
            'nat_mac': nat_mac, 'hostonly_mac': lab_mac, 'seed_iso': str(seed),
            'create_commands_for_review_only': commands,
            'start_command_for_later_proof': ['VBoxManage', 'startvm', vm_id, '--type=headless'],
            'after_install_poweroff_commands_for_review': [
                ['VBoxManage', 'storageattach', vm_id, '--storagectl=SATA', '--port=1', '--device=0', '--type=dvddrive', '--medium=none'],
                ['VBoxManage', 'storageattach', vm_id, '--storagectl=SATA', '--port=2', '--device=0', '--type=dvddrive', '--medium=none'],
                ['VBoxManage', 'modifyvm', vm_id, '--boot1=disk', '--boot2=none']]}


def prepare(spec_path, iso_path, receipt_path, public_key_path, runtime_root, output):
    spec = validate(load_json(spec_path))
    if spec['profile'] != 'lab' or spec['platform'] != {'kind': 'virtualbox', 'architecture': 'aarch64', 'cpu_model': 'native'}:
        raise ValueError('This preparation tool supports the ARM64 VirtualBox learning profile only')
    if not spec['image']['format'] == 'iso' or spec['image']['qualified']:
        raise ValueError('Use the candidate installer profile; preparation does not qualify a running image')
    receipt = load_json(receipt_path)
    if not all([receipt.get('signature_verified'), receipt.get('checksum_verified'),
                receipt.get('signing_fingerprint') == SIGNING_FINGERPRINT]):
        raise ValueError('A verified Ubuntu source receipt is required')
    iso = iso_path.resolve()
    if iso.name != 'ubuntu-26.04.1-live-server-arm64.iso':
        raise ValueError('Expected the selected Ubuntu Server ARM64 installer, not another architecture/image')
    if digest(iso) != receipt['sha256'] or receipt['sha256'] != spec['image']['sha256']:
        raise ValueError('ISO digest, verification receipt and specification must match')
    if public_key_path.suffix != '.pub':
        raise ValueError('Provide an SSH .pub file, never a private key')
    key = public_key_path.read_text().strip()
    if not re.match(r'^(ssh-ed25519|ecdsa-sha2-nistp256|ssh-rsa) [A-Za-z0-9+/=]+(?: [^\n]*)?$', key):
        raise ValueError('Invalid public key format')
    if output.exists():
        raise FileExistsError('Preparation destination already exists; use a fresh private directory')
    runtime = runtime_root.resolve()
    root = private_output(output)
    if not root.is_relative_to(runtime):
        raise ValueError('Preparation must be inside the private runtime root')
    namespace = uuid.uuid4()
    staging = root / 'boot'; staging.mkdir(mode=0o700)
    for name in ['grub.cfg', 'md5sum.txt']:
        source = '/boot/grub/grub.cfg' if name == 'grub.cfg' else '/md5sum.txt'
        run(['xorriso', '-osirrox', 'on', '-indev', str(iso), '-extract', source, str(staging / name)])
        # xorriso preserves the ISO's read-only file mode; the private copies
        # need to be writable so the boot argument and matching manifest can
        # be updated without changing the source installer.
        os.chmod(staging / name, 0o600)
    grub = patch_grub((staging / 'grub.cfg').read_text())
    (staging / 'grub.cfg').write_text(grub)
    md5 = update_md5((staging / 'md5sum.txt').read_text(), 'boot/grub/grub.cfg', grub.encode())
    (staging / 'md5sum.txt').write_text(md5)
    installer = root / 'ubuntu-server-arm64-autoinstall.iso'
    print('Preparing shared autoinstall ISO; source installer remains unchanged.', flush=True)
    run(['xorriso', '-indev', str(iso), '-outdev', str(installer), '-boot_image', 'any', 'replay',
         '-map', str(staging / 'grub.cfg'), '/boot/grub/grub.cfg',
         '-map', str(staging / 'md5sum.txt'), '/md5sum.txt', '-commit', '-end'])
    report = run(['xorriso', '-indev', str(installer), '-report_el_torito', 'plain'])
    if 'UEFI' not in report:
        raise ValueError('Prepared media did not retain UEFI boot metadata')
    (root / 'uefi-boot-report.txt').write_text(report)
    network = ipaddress.ip_network(spec['network']['node_cidr'])
    network_name = f'onprem-{spec["name"]}-{str(namespace)[:8]}'
    vbox_network_name = f'hostonly-{network_name}'
    manifest = {'schema_version': 1, 'status': 'prepared-only; no VirtualBox commands executed',
                'namespace': str(namespace), 'runtime_root': str(runtime),
                'spec': str(spec_path.resolve()), 'source_iso_sha256': receipt['sha256'],
                'installer_iso': str(installer), 'installer_sha256': digest(installer), 'boot_qualified': False,
                'network': {'name': network_name, 'attachment_name': network_name,
                            'vbox_network_name': vbox_network_name, 'cidr': str(network),
                            'create_command_for_review': ['VBoxManage', 'hostonlynet', 'add', '--name=' + network_name,
                                '--netmask=' + str(network.netmask), '--lower-ip=' + str(network.network_address + 1),
                                '--upper-ip=' + str(network.network_address + 9), '--enable']}, 'nodes': {}}
    for name, node in expanded_nodes(spec).items():
        directory = root / name;directory.mkdir(mode=0o700)
        cidata = directory / 'cidata';cidata.mkdir(mode=0o700)
        user_data, metadata, nat_mac, lab_mac = seed_config(spec, name, namespace, key)
        for filename, value in [('user-data', user_data), ('meta-data', metadata)]:
            target = cidata / filename
            target.write_text(('#cloud-config\n' if filename == 'user-data' else '') + yaml.safe_dump(value, sort_keys=False))
            os.chmod(target, 0o600)
        seed_iso = directory / 'seed.iso'
        run(['xorriso', '-as', 'mkisofs', '-V', 'cidata', '-J', '-r', '-o', str(seed_iso), str(cidata)])
        manifest['nodes'][name] = planned_commands(spec, name, node, namespace, runtime, installer, seed_iso,
                                                   network_name, nat_mac, lab_mac)
        manifest['nodes'][name]['seed_sha256'] = digest(seed_iso)
        print(f'Prepared {name}: {node["cpus"]} CPU, {node["memory_mib"]} MiB, {node["root_disk_gib"]} GiB disk intent.', flush=True)
    write_private(root / 'virtualbox-plan.json', manifest)
    print('Preparation complete. No VMs, VM disks or networks were created or started.', flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--iso', type=Path, required=True)
    parser.add_argument('--verification-receipt', type=Path, required=True)
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.spec, args.iso, args.verification_receipt, args.public_key, args.runtime_root, args.output)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        print('ERROR:', error, file=sys.stderr)
        sys.exit(1)
