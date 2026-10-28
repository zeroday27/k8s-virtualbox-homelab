"""Validate baseline policy values before inserting them in privileged configurations."""
import ipaddress
import re
from ansible.errors import AnsibleFilterError


def network_policy(policy):
    def hosts(values, label):
        if not isinstance(values, list) or not values:
            raise ValueError(label + ' requires explicit individual IPv4 hosts')
        result = []
        for value in values:
            network = ipaddress.ip_network(str(value), strict=True)
            if network.version != 4 or network.prefixlen != 32:
                raise ValueError(label + ' must contain individual IPv4 /32 hosts')
            address = str(network.network_address)
            if network.network_address.is_unspecified or network.network_address.is_multicast or address == '255.255.255.255':
                raise ValueError('Invalid host address')
            if address in result:
                raise ValueError('Duplicate ' + label + ' address')
            result.append(address)
        return result
    try:
        nodes = hosts(policy['nodes'], 'nodes')
        controls = hosts(policy['controls'], 'controls')
        bastions = hosts(policy['bastions'], 'bastions')
        if not set(controls) <= set(nodes):
            raise ValueError('Control planes must be cluster nodes')
        if policy['role'] not in ['control_plane', 'worker']:
            raise ValueError('Declare control_plane or worker role')
        source = str(ipaddress.IPv4Address(policy['source']))
        if source not in bastions:
            raise ValueError('The current SSH source is outside the bastion allowlist')
        transport = policy['transport']
        if transport not in ['ipip', 'vxlan', 'none']:
            raise ValueError('Select a reviewed Calico transport: ipip, vxlan or none')
        pods = []
        for value in policy['pods']:
            network = ipaddress.ip_network(str(value), strict=True)
            if network.version != 4 or network.prefixlen < 8 or any(ipaddress.ip_address(n) in network for n in nodes + bastions):
                raise ValueError('Pod networks must be scoped IPv4 CIDRs separate from nodes/bastions')
            pods.append(str(network))
        ports = {}
        for key in ['ssh_port', 'api_port', 'kubelet_port']:
            value = policy[key]
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
                raise ValueError('Invalid port: ' + key)
            ports[key] = value
        if type(policy['nodeport_enabled']) is not bool or type(policy['metrics']) is not bool:
            raise ValueError('Feature flags must be YAML booleans')
        nodeports = hosts(policy['nodeport_sources'], 'NodePort clients') if policy['nodeport_enabled'] else []
        port_range = str(policy['nodeport_range'])
        if not re.fullmatch(r'[0-9]+-[0-9]+', port_range):
            raise ValueError('Use an absolute NodePort range')
        low, high = map(int, port_range.split('-'))
        if not 1 <= low <= high <= 65535:
            raise ValueError('Invalid NodePort range')
        return dict(nodes=nodes, controls=controls, bastions=bastions, pods=pods,
                    role=policy['role'], transport=transport, ports=ports,
                    nodeport_sources=nodeports, nodeport_range=port_range, metrics=policy['metrics'])
    except (KeyError, TypeError, ValueError) as error:
        raise AnsibleFilterError(str(error)) from error


def lvm_devices_safe(blocks, requested, pvs, vg):
    """Allow only whole, unused disks or existing PVs of this exact VG; reject root ancestry."""
    def walk(block):
        yield block
        for child in block.get('children', []):
            yield from walk(child)
    try:
        if not requested or len(set(requested)) != len(requested):
            raise ValueError('Declare distinct extra data disks')
        roots = {b['name']: b for b in blocks['blockdevices']}
        root_disks = {name for name, block in roots.items()
                      if any('/' in (child.get('mountpoints') or []) for child in walk(block))}
        if any(pv['pv_name'].strip() in root_disks and pv['vg_name'].strip() == vg for pv in pvs):
            raise ValueError('The requested VG also owns a root disk')
        for device in requested:
            if device not in roots or roots[device]['type'] != 'disk':
                raise ValueError('LVM devices must be observed whole disks')
            block = roots[device]
            descendants = list(walk(block))
            if any('/' in (b.get('mountpoints') or []) for b in descendants):
                raise ValueError('Refusing the root filesystem disk')
            own_pv = next((pv for pv in pvs if pv['pv_name'].strip() == device), None)
            if own_pv:
                if own_pv['vg_name'].strip() != vg:
                    raise ValueError('PV belongs to another or an unowned VG')
            elif len(descendants) != 1 or block.get('fstype') or any(block.get('mountpoints') or []):
                raise ValueError('Refusing an occupied or partitioned data disk')
        return True
    except (KeyError, TypeError, ValueError) as error:
        raise AnsibleFilterError(str(error)) from error


class FilterModule:
    def filters(self):
        return {'baseline_network_policy': network_policy, 'baseline_lvm_devices_safe': lvm_devices_safe}
