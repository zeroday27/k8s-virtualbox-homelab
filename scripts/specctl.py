#!/usr/bin/env python3
"""Validate cluster intent and compile private planning or observed Ansible inputs."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def load_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique_pairs)


def expanded_nodes(spec):
    return {name: {**node, **spec['node_classes'][node['class']]}
            for name, node in spec['nodes'].items()}


def validate(spec, deployment=False):
    schema = load_json(ROOT / 'specs/cluster.schema.json')
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(spec),
                    key=lambda error: str(error.path))
    if errors:
        raise ValueError('; '.join(f'{list(e.path)}: {e.message}' for e in errors))
    networks = [ipaddress.ip_network(spec['network'][key], strict=True)
                for key in ['node_cidr', 'pod_cidr', 'service_cidr']]
    if any(net.version != 4 for net in networks):
        raise ValueError('This contract currently supports IPv4 only')
    for index, network in enumerate(networks):
        if any(network.overlaps(other) for other in networks[index + 1:]):
            raise ValueError('Node, pod and Service networks must not overlap')
    node_network = networks[0]
    addresses = [ipaddress.ip_address(n['ip']) for n in spec['nodes'].values()]
    vip = ipaddress.ip_address(spec['network']['api_vip'])
    first = ipaddress.ip_address(spec['network']['service_pool_start'])
    last = ipaddress.ip_address(spec['network']['service_pool_end'])
    if first > last:
        raise ValueError('Service pool start must not exceed end')
    for address in [*addresses, first, last]:
        if address not in node_network or address in [node_network.network_address, node_network.broadcast_address]:
            raise ValueError('Node, VIP and service pool addresses must be usable addresses in node_cidr')
    if spec['components']['api_endpoint'] == 'kube_vip':
        if vip not in node_network or vip in [node_network.network_address, node_network.broadcast_address]:
            raise ValueError('ARP API VIP must be usable in node_cidr')
    elif any(vip in network for network in networks[1:]):
        raise ValueError('External API endpoint must not be inside pod or Service CIDRs')
    node_endpoint = spec['components']['api_endpoint'] == 'node'
    if len(set(addresses)) != len(addresses) or (vip in addresses and not node_endpoint):
        raise ValueError('Duplicate node address or API VIP collision')
    if any(first <= address <= last for address in [*addresses, vip]):
        raise ValueError('Service pool overlaps node addresses or API VIP')
    gateway = spec['network']['gateway']
    if gateway:
        gateway = ipaddress.ip_address(gateway)
        if gateway not in node_network or gateway in addresses or gateway == vip or first <= gateway <= last:
            raise ValueError('Gateway must be in node_cidr and separate from node/VIP/pool addresses')
    for cidr in spec['security']['management_cidrs']:
        if ipaddress.ip_network(cidr, strict=True).prefixlen == 0:
            raise ValueError('Management access must not be open to the entire Internet')
    if spec['security']['ssh_user'] == 'root':
        raise ValueError('Use a non-root bootstrap SSH user')
    if spec['image']['architecture'] != spec['platform']['architecture']:
        raise ValueError('Image and platform architectures differ')
    if spec['platform']['kind'] == 'proxmox' and spec['platform']['architecture'] != 'x86_64':
        raise ValueError('This Proxmox adapter is qualified for x86_64 only; ARM requires a separate proof')
    nodes = expanded_nodes(spec)  # Raises on an undefined class.
    controls = [n for n in nodes.values() if n['role'] == 'control_plane']
    workers = [n for n in nodes.values() if n['role'] == 'worker']
    allowed_controls = [1, 3, 5] if spec['profile'] == 'lab' else [3, 5]
    if len(controls) not in allowed_controls or len(workers) < 2:
        raise ValueError('Lab requires one/three/five control planes; production requires three/five; both require at least two workers')
    if node_endpoint and (spec['profile'] != 'lab' or len(controls) != 1 or str(vip) != controls[0]['ip']):
        raise ValueError('Node API endpoint requires a single-control-plane lab and its control-plane IP')
    for node in nodes.values():
        if node['role'] == 'control_plane' and (node['cpus'] < 2 or node['memory_mib'] < 2048):
            raise ValueError('Control planes require at least two CPUs and 2048 MiB')
        if any(not key.startswith('scsi') or not key[4:].isdigit() or not 1 <= int(key[4:]) <= 30
               for key in node['data_disks']):
            raise ValueError('Data disks use scsi1 through scsi30; scsi0 is reserved for root')
    for host in {n['hypervisor_host'] for n in nodes.values()}:
        if len({n['failure_domain'] for n in nodes.values() if n['hypervisor_host'] == host}) != 1:
            raise ValueError('One physical hypervisor host cannot claim multiple independent failure domains')
    if spec['components']['api_endpoint'] == 'kube_vip' and len({n['interface'] for n in controls}) != 1:
        raise ValueError('The current kube-vip adapter requires the same interface name on all control planes')
    lock = load_json(ROOT / 'versions.lock.json')
    for key, expected in [('kubespray_release', lock['kubespray']['release']), ('kubernetes', lock['kubespray']['kubernetes'])]:
        if spec['versions'][key] != expected:
            raise ValueError(f'{key} must match the reviewed version bundle')
    if spec['profile'] == 'production':
        if len({n['failure_domain'] for n in controls}) < 3 or len({n['hypervisor_host'] for n in controls}) < 3:
            raise ValueError('Production control planes require three independent physical failure domains')
        if len({n['failure_domain'] for n in workers}) < 2:
            raise ValueError('Production workers require at least two failure domains')
        if any(n['memory_mib'] < 4096 or n['cpus'] < 2 or n['root_disk_gib'] < 40 for n in nodes.values()):
            raise ValueError('Production sizing floor is two CPUs, 4096 MiB and 40 GiB; workload sizing is still required')
        security = spec['security']
        if not all([security['secrets_encryption'], security['audit'], security['oidc_issuer'], security['oidc_client_id'], security['pod_security'] == 'restricted']):
            raise ValueError('Production requires encryption, audit, OIDC and restricted workload admission')
        components = spec['components']
        if components['etcd_mode'] != 'host':
            raise ValueError('The pinned Kubespray kubeadm etcd mode is experimental; production requires host mode')
        if components['cni'] == 'flannel' or components['gitops'] == 'none' or components['storage_driver'] != 'csi_external' or not components['storage_class']:
            raise ValueError('Production requires NetworkPolicy-capable CNI, GitOps and an explicitly qualified CSI class')
        if not all(components[key] for key in ['cert_manager', 'monitoring', 'logging', 'metrics_server']) or components['policy_engine'] == 'none':
            raise ValueError('Production security and observability components are required')
        if not all([spec['dr']['enabled'], spec['dr']['independent_backup'], spec['dr']['backup_target_ref']]):
            raise ValueError('Production needs an independently recoverable backup destination')
    if deployment:
        if not spec['image']['qualified'] or not spec['image']['sha256'] or lock['qualification'] != 'qualified':
            raise ValueError('Deployment blocked: image checksum and qualified release bundle are required')
        if spec['profile'] == 'production' and (not spec['dr']['evidence_ref'] or lock['addons']['qualification'] != 'qualified'):
            raise ValueError('Production deployment requires restore evidence and qualified add-on versions/digests')
    return spec


def inventory(spec, facts=None):
    nodes = expanded_nodes(spec)
    if facts is not None:
        observations = facts.get('provisioned_nodes', {}).get('value')
        if not isinstance(observations, dict) or set(observations) != set(nodes):
            raise ValueError('Terraform observations must exactly match the specification node set')
        identities = set()
        for name, node in nodes.items():
            actual = observations[name]
            if (not actual.get('id') or actual.get('ip') != node['ip']
                    or node['ip'] not in actual.get('observed_ips', [])
                    or actual.get('hypervisor_host') != node['hypervisor_host']
                    or actual.get('image_build_id') != spec['image']['build_id']):
                raise ValueError(f'Observed VM identity, address, placement or image mismatch: {name}')
            identity = str(actual['id'])
            if identity in identities:
                raise ValueError('Two node names resolve to the same VM identity')
            identities.add(identity)
    hosts = {name: {'ansible_host': node['ip'], 'ip': node['ip'], 'access_ip': node['ip'],
                    'node_labels': {'topology.kubernetes.io/zone': node['failure_domain']},
                    'baseline_expected_interface': node['interface'],
                    'flannel_interface': node['interface'],
                    'calico_ip_auto_method': 'interface=' + node['interface'],
                    'baseline_expected_architecture': spec['platform']['architecture'],
                    'baseline_expected_release': spec['image']['release'],
                    'baseline_expected_memory_mib': node['memory_mib']}
             for name, node in nodes.items()}
    controls = {name: {} for name, n in nodes.items() if n['role'] == 'control_plane'}
    workers = {name: {} for name, n in nodes.items() if n['role'] == 'worker'}
    return {'all': {'vars': {'ansible_user': spec['security']['ssh_user'],
                            'ansible_python_interpreter': '/usr/bin/python3',
                            'baseline_access_verified': False,
                            'baseline_ntp_servers': spec['network']['ntp_servers']},
                    'hosts': hosts, 'children': {
                        'kube_control_plane': {'hosts': controls}, 'control_plane': {'hosts': controls},
                        'kube_node': {'hosts': workers}, 'workers': {'hosts': workers},
                        'etcd': {'hosts': controls},
                        'k8s_cluster': {'children': {'kube_control_plane': {}, 'kube_node': {}}}}}}


def kubespray_vars(spec):
    network = spec['network']
    vip = spec['components']['api_endpoint'] == 'kube_vip'
    control = next(n for n in spec['nodes'].values() if n['role'] == 'control_plane')
    result = {'kube_version': spec['versions']['kubernetes'], 'container_manager': 'containerd',
            'etcd_deployment_type': spec['components']['etcd_mode'],
            'upstream_dns_servers': network['dns_servers'],
            'ntp_enabled': False,
            'kube_oidc_auth': spec['security']['oidc_issuer'] is not None,
            'kube_oidc_url': spec['security']['oidc_issuer'] or '',
            'kube_oidc_client_id': spec['security']['oidc_client_id'] or '',
            'kube_oidc_username_claim': 'sub', 'kube_oidc_username_prefix': 'oidc:',
            'kube_oidc_groups_claim': 'groups', 'kube_oidc_groups_prefix': 'oidc:',
            'kube_network_plugin': spec['components']['cni'], 'kube_pods_subnet': network['pod_cidr'],
            'kube_service_addresses': network['service_cidr'], 'kube_proxy_mode': 'iptables',
            'kube_apiserver_port': network['api_port'],
            'kube_vip_enabled': vip, 'kube_vip_controlplane_enabled': vip,
            'kube_vip_services_enabled': False, 'kube_vip_arp_enabled': vip,
            'kube_vip_interface': control['interface'], 'kube_vip_address': network['api_vip'],
            'loadbalancer_apiserver': {'address': network['api_vip'], 'port': network['api_port']},
            'supplementary_addresses_in_ssl_keys': [network['api_vip']],
            'kube_encrypt_secret_data': spec['security']['secrets_encryption'],
            'kubernetes_audit': spec['security']['audit'], 'metallb_enabled': False}
    if spec['components']['api_endpoint'] == 'node':
        # Connect directly; do not deploy Kubespray's local nginx API proxy.
        result['loadbalancer_apiserver_localhost'] = False
    return result


def private_output(path):
    path = path.resolve()
    if path.is_relative_to(ROOT):
        relative = str(path.relative_to(ROOT)) + '/.private-output'
        result = subprocess.run(['git', '-C', str(ROOT), 'check-ignore', '--quiet', relative])
        if result.returncode != 0:
            raise ValueError('Generated inventory must be outside the checkout or inside an ignored directory')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def write_private(path, value):
    # Refuse symlinks and existing files rather than overwriting private material.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['validate', 'render'])
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--deployment', action='store_true')
    parser.add_argument('--facts', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    spec = validate(load_json(args.spec), deployment=args.deployment or args.facts is not None)
    if args.command == 'render':
        if args.output is None:
            parser.error('render needs --output')
        inv = inventory(spec, load_json(args.facts) if args.facts else None)
        out = private_output(args.output)
        write_private(out / ('inventory.json' if args.facts else 'inventory.preview.json'), inv)
        write_private(out / 'kubespray-vars.json', kubespray_vars(spec))
        write_private(out / 'terraform.tfvars.json', {'spec_file': str(args.spec.resolve())})
        write_private(out / 'components.intent.json', {'components': spec['components'], 'security': spec['security'], 'dr': spec['dr']})
        print('Rendered private inputs; inventory is a preview only.' if not args.facts else 'Rendered inventory from matched VM observations.')
    else:
        print(f"Valid specification: {spec['name']} ({spec['profile']}); deployment qualification is a separate gate.")


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
