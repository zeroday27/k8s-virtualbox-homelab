#!/usr/bin/env python3
"""Prepare a private first-boot NoCloud seed for one full clone. Never run VBoxManage."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import uuid

import yaml

from prepare_virtualbox import mac
from specctl import load_json, private_output, validate


def clone_seed(spec, name, instance_id, public_key):
    validate(spec)
    if spec['profile'] != 'lab' or spec['platform']['kind'] != 'virtualbox' or spec['platform']['architecture'] != 'aarch64':
        raise ValueError('Clone seeds are limited to the ARM64 VirtualBox lab')
    if name not in spec['nodes']:
        raise ValueError('Node must exist in the specification')
    namespace = uuid.UUID(instance_id)
    if not re.fullmatch(r'(ssh-ed25519|ecdsa-sha2-nistp256|ssh-rsa) [A-Za-z0-9+/=]+(?: [^\n]*)?', public_key):
        raise ValueError('Provide one OpenSSH public key, never private key material')
    node = spec['nodes'][name]
    prefix = ipaddress.ip_network(spec['network']['node_cidr']).prefixlen
    nat_mac, lab_mac = (mac(namespace, name, nic) for nic in ['nat', 'lab'])
    marker = 'CLONE_HOST_KEY_' + namespace.hex
    emit = ("from pathlib import Path; Path('/dev/ttyAMA0').write_text("
            + repr('\n' + marker + '_BEGIN\n')
            + " + Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text() + "
            + repr('\n' + marker + '_END\n') + ")")
    user_data = {
        'hostname': name, 'preserve_hostname': False, 'manage_etc_hosts': True,
        'users': [{'name': spec['security']['ssh_user'], 'groups': ['adm', 'sudo'],
                   'shell': '/bin/bash', 'lock_passwd': True,
                   'sudo': ['ALL=(ALL) NOPASSWD:ALL'], 'ssh_authorized_keys': [public_key]}],
        'disable_root': True, 'ssh_pwauth': False, 'ssh_deletekeys': True,
        'ssh_genkeytypes': ['rsa', 'ecdsa', 'ed25519'],
        'runcmd': [['python3', '-c', emit]]}
    metadata = {'instance-id': str(namespace), 'local-hostname': name}
    network = {'version': 2, 'renderer': 'networkd', 'ethernets': {
        'nat0': {'match': {'macaddress': nat_mac}, 'set-name': 'nat0', 'dhcp4': True,
                 'dhcp6': False, 'dhcp4-overrides': {'route-metric': 100},
                 'nameservers': {'addresses': spec['network']['dns_servers']}},
        node['interface']: {'match': {'macaddress': lab_mac}, 'set-name': node['interface'],
                            'dhcp4': False, 'dhcp6': False, 'link-local': [],
                            'addresses': [f"{node['ip']}/{prefix}"]}}}
    if node['interface'] != 'lab0':
        raise ValueError('The fixed-slot ARM64 template requires the lab0 interface')
    return {'user-data': user_data, 'meta-data': metadata, 'network-config': network,
            'identity': {'instance_id': str(namespace), 'node': name, 'ip': node['ip'],
                         'nat_mac': nat_mac, 'lab_mac': lab_mac, 'host_key_marker': marker}}


def prepare(spec, name, instance_id, public_key, output):
    data = clone_seed(spec, name, instance_id, public_key)
    if output.exists():
        raise FileExistsError('Use a new private destination; existing seeds are never overwritten')
    root = private_output(output)
    for filename, value in data.items():
        path = root / (filename + '.json' if filename == 'identity' else filename)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            if filename == 'identity':
                json.dump(value, stream, indent=2)
                stream.write('\n')
            else:
                if filename == 'user-data':
                    stream.write('#cloud-config\n')
                yaml.safe_dump(value, stream, sort_keys=False)
    return data['identity']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--node', required=True)
    parser.add_argument('--instance-id', required=True, help='Fresh UUID of this clone, not the template UUID')
    parser.add_argument('--public-key', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.public_key.suffix != '.pub':
        parser.error('Provide a .pub file')
    identity = prepare(load_json(args.spec), args.node, args.instance_id,
                       args.public_key.read_text().strip(), args.output)
    print(json.dumps(identity, indent=2))
    print('Seed files prepared; create a cidata ISO separately. No VM was changed.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit('ERROR: ' + str(error))
