"""Validate node/CNI inputs before privileged configuration rendering."""
import ipaddress
import re
from ansible.errors import AnsibleFilterError


def network_policy(settings):
    try:
        node = ipaddress.IPv4Address(settings['node_ip'])
        pods = ipaddress.ip_network(settings['pod_cidr'], strict=True)
        services = ipaddress.ip_network(settings['service_cidr'], strict=True)
        if node.is_loopback or node.is_unspecified or node.is_multicast:
            raise ValueError('Use a real static node address')
        if any(n.version != 4 or n.prefixlen < 8 for n in [pods, services]):
            raise ValueError('Use scoped IPv4 pod and service networks')
        if pods.overlaps(services) or node in pods or node in services:
            raise ValueError('Node, pod and service networks must not overlap')
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', settings['interface']):
            raise ValueError('Invalid node interface')
        if settings['transport'] != 'ipip':
            raise ValueError('Only the reviewed Calico IPIP/BGP profile is implemented')
        return dict(node_ip=str(node), pod_cidr=str(pods), service_cidr=str(services))
    except (KeyError, TypeError, ValueError) as error:
        raise AnsibleFilterError(str(error)) from error


def architecture(value):
    aliases = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'amd64', 'amd64': 'amd64'}
    if value not in aliases:
        raise AnsibleFilterError('Unsupported guest architecture: ' + str(value))
    return aliases[value]


def artifact_contract(bom, arch):
    try:
        artifacts = bom['artifacts_by_arch'][arch]
        expected = {'containerd', 'runc', 'crictl', 'kubeadm', 'kubelet', 'kubectl', 'kustomize'}
        if len(artifacts) != len(expected) or {a['name'] for a in artifacts} != expected:
            raise ValueError('Missing or duplicated locked artifacts')
        for a in artifacts:
            version = bom['versions']['kubernetes' if a['name'] in ['kubeadm', 'kubelet', 'kubectl'] else a['name']]
            if a['version'] != version or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
                raise ValueError('Artifact version must match the BOM')
            if arch not in a['url'] or not a['url'].startswith(('https://github.com/', 'https://dl.k8s.io/')):
                raise ValueError('Wrong architecture or source for artifact')
            if not re.fullmatch(r'[a-f0-9]{64}', a['sha256']):
                raise ValueError('Missing artifact SHA256')
            if a['scope'] != ('control_plane' if a['name'] in ['kubectl', 'kustomize'] else 'all'):
                raise ValueError('Wrong installation scope')
            if a['kind'] not in ['tar', 'binary']:
                raise ValueError('Invalid artifact format')
            for f in a['files']:
                if f['dest'] not in ['/usr/local/bin/' + f['name'], '/usr/local/sbin/runc']:
                    raise ValueError('Unexpected privileged destination')
                if not re.fullmatch(r'[a-z0-9-]+', f['name']) or not re.fullmatch(r'(bin/)?[a-z0-9-]+', f['source']):
                    raise ValueError('Unsafe artifact file path')
        return artifacts
    except (KeyError, TypeError, ValueError) as error:
        raise AnsibleFilterError(str(error)) from error


class FilterModule:
    def filters(self):
        return {'k8s_base_network_policy': network_policy, 'k8s_base_architecture': architecture,
                'k8s_base_artifact_contract': artifact_contract}
