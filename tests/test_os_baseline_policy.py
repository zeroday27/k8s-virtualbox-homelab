"""Exercise privileged policy boundaries using synthetic addresses and disks."""
import copy
import importlib.util
from pathlib import Path
import unittest
import shlex
import subprocess
from ansible.errors import AnsibleFilterError
from jinja2 import Environment, FileSystemLoader

ROLE = Path(__file__).resolve().parents[1] / 'ansible/roles/os_baseline'
SPEC = importlib.util.spec_from_file_location('baseline_policy', ROLE / 'filter_plugins/baseline_policy.py')
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class NetworkPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = dict(nodes=['192.0.2.11', '192.0.2.21'], controls=['192.0.2.11'],
                           bastions=['192.0.2.1/32'], source='192.0.2.1', role='control_plane',
                           pods=['10.244.0.0/16'], transport='ipip', ssh_port=22, api_port=6443,
                           kubelet_port=10250, nodeport_enabled=False, nodeport_sources=[],
                           nodeport_range='30000-32767', metrics=False)

    def render(self, **changes):
        policy = dict(self.policy, **changes)
        env = Environment(loader=FileSystemLoader(ROLE / 'templates'))
        return env.get_template('os-baseline.nft.j2').render(baseline_firewall_policy=POLICY.network_policy(policy))

    def test_control_plane_and_worker_expose_different_listeners(self):
        control, worker = self.render(), self.render(role='worker')
        self.assertIn('tcp dport 6443 accept', control)
        self.assertIn('2379, 2380', control)
        self.assertNotIn('6443', worker)
        self.assertNotIn('2379', worker)
        self.assertNotIn('30000-32767', worker)
        self.assertIn('ip saddr @bastions tcp dport 22', worker)
        self.assertNotIn('hook forward', worker)
        self.assertNotIn('flush ruleset', worker.replace('# Only this table is replaced atomically. Never flush ruleset or CNI tables.', ''))

    def test_only_reviewed_inbound_service_rules_are_rendered(self):
        shared = {
            'ip saddr @bastions tcp dport 22 accept',
            'ip saddr @controls tcp dport 10250 accept',
            'ip saddr @nodes tcp dport 179 accept',
        }
        control = {
            'ip saddr @nodes tcp dport 6443 accept',
            'ip saddr @bastions tcp dport 6443 accept',
            'ip saddr { 10.244.0.0/16 } tcp dport 6443 accept',
            'ip saddr @controls tcp dport { 2379, 2380 } accept',
        }
        for role, expected in [('control_plane', shared | control), ('worker', shared)]:
            text = self.render(role=role)
            tcp = {line.strip() for line in text.splitlines() if 'tcp dport' in line}
            udp = {line.strip() for line in text.splitlines() if 'udp dport' in line}
            with self.subTest(role=role):
                self.assertEqual(tcp, expected)
                self.assertEqual(udp, {'iifname "nat0" udp sport 67 udp dport 68 accept'})
                self.assertIn('policy drop;', text)
                self.assertNotIn('meta l4proto ipv6-icmp accept', text)
                ipv6 = next(line for line in text.splitlines() if 'icmpv6 type' in line)
                self.assertNotIn('echo-request', ipv6)
                self.assertNotIn('echo-reply', ipv6)

    def test_transport_rules_are_scoped_to_selected_mode(self):
        ipip, vxlan = self.render(), self.render(transport='vxlan')
        self.assertIn('ip protocol 4 accept', ipip)
        self.assertIn('udp dport 4789 accept', vxlan)
        self.assertNotIn('tcp dport 179', vxlan)
        self.assertNotIn('ip protocol 4 accept', vxlan)

    def test_nodeport_requires_explicit_clients_and_worker_role(self):
        with self.assertRaises(AnsibleFilterError):
            self.render(nodeport_enabled=True)
        worker = self.render(role='worker', nodeport_enabled=True, nodeport_sources=['198.51.100.2'])
        self.assertIn('ip saddr { 198.51.100.2 } tcp dport 30000-32767', worker)
        self.assertNotIn('30000-32767', self.render(nodeport_enabled=True, nodeport_sources=['198.51.100.2']))

    def test_ansible_tagged_integer_subclasses_are_accepted(self):
        class TaggedInt(int):
            pass
        self.assertIn('tcp dport 22', self.render(ssh_port=TaggedInt(22)))

    def test_unsafe_allowlists_and_values_are_rejected(self):
        for changes in [dict(bastions=['0.0.0.0/0']), dict(source='192.0.2.99'),
                        dict(controls=['192.0.2.99']), dict(transport='bad; flush ruleset'),
                        dict(nodes=['192.0.2.11/24']), dict(ssh_port=True),
                        dict(nodeport_enabled='false'), dict(pods=['192.0.2.0/24']),
                        dict(nodeport_range='65535-99999')]:
            with self.subTest(changes=changes), self.assertRaises(AnsibleFilterError):
                self.render(**changes)


class StoragePolicyTests(unittest.TestCase):
    def setUp(self):
        self.blocks = {'blockdevices': [dict(name='/dev/sda', type='disk', fstype=None, mountpoints=[None],
            children=[dict(name='/dev/sda2', type='part', fstype='ext4', mountpoints=['/'])]),
            dict(name='/dev/sdb', type='disk', fstype=None, mountpoints=[None])]}

    def test_blank_extra_disk_allowed(self):
        self.assertTrue(POLICY.lvm_devices_safe(self.blocks, ['/dev/sdb'], [], 'vg_k8s'))

    def test_root_partition_missing_and_duplicate_disks_rejected(self):
        for devices in [['/dev/sda'], ['/dev/sda2'], ['/dev/missing'], ['/dev/sdb', '/dev/sdb']]:
            with self.subTest(devices=devices), self.assertRaises(AnsibleFilterError):
                POLICY.lvm_devices_safe(self.blocks, devices, [], 'vg_k8s')

    def test_foreign_and_unowned_pvs_rejected(self):
        for vg in ['foreign', '']:
            with self.subTest(vg=vg), self.assertRaises(AnsibleFilterError):
                POLICY.lvm_devices_safe(self.blocks, ['/dev/sdb'], [dict(pv_name='/dev/sdb', vg_name=vg)], 'vg_k8s')

    def test_occupied_extra_disk_rejected(self):
        for changes in [dict(fstype='ext4'), dict(mountpoints=['/srv/existing']),
                        dict(children=[dict(name='/dev/sdb1', type='part', mountpoints=[None])])]:
            blocks = copy.deepcopy(self.blocks)
            blocks['blockdevices'][1].update(changes)
            with self.subTest(changes=changes), self.assertRaises(AnsibleFilterError):
                POLICY.lvm_devices_safe(blocks, ['/dev/sdb'], [], 'vg_k8s')

    def test_owned_pv_can_be_reused_but_root_still_rejected(self):
        self.assertTrue(POLICY.lvm_devices_safe(self.blocks, ['/dev/sdb'], [dict(pv_name='/dev/sdb', vg_name='vg_k8s')], 'vg_k8s'))
        with self.assertRaises(AnsibleFilterError):
            POLICY.lvm_devices_safe(self.blocks, ['/dev/sda'], [dict(pv_name='/dev/sda', vg_name='vg_k8s')], 'vg_k8s')


class RecoveryTemplateTests(unittest.TestCase):
    def test_both_first_install_and_existing_service_render_valid_shell(self):
        env = Environment(loader=FileSystemLoader(ROLE / 'templates'))
        env.filters['quote'] = shlex.quote
        for existing in [False, True]:
            file = {'changed': True}
            unit = {'changed': True}
            services = {}
            if existing:
                file['backup_file'] = '/etc/example backup'
                unit['backup_file'] = '/etc/unit backup'
                services['os-baseline-firewall.service'] = {'status': 'enabled', 'state': 'running'}
            text = env.get_template('firewall-rollback.sh.j2').render(
                baseline_firewall_file=file, baseline_firewall_unit=unit,
                ansible_facts={'services': services})
            with self.subTest(existing=existing):
                subprocess.run(['sh', '-n'], input=text, text=True, check=True)
                self.assertIn('trap restore_table 0', text)
                self.assertNotIn('flush ruleset', text)

    def test_shared_root_volume_group_rejected_even_for_a_new_disk(self):
        blocks = {'blockdevices': [dict(name='/dev/sda', type='disk', mountpoints=[None],
            children=[dict(name='/dev/mapper/vg-root', type='lvm', mountpoints=['/'])]),
            dict(name='/dev/sdb', type='disk', fstype=None, mountpoints=[None])]}
        with self.assertRaises(AnsibleFilterError):
            POLICY.lvm_devices_safe(blocks, ['/dev/sdb'], [dict(pv_name='/dev/sda', vg_name='vg_k8s')], 'vg_k8s')


class HostsEntryTests(unittest.TestCase):
    def test_all_peers_render_in_one_stable_block(self):
        entries = [dict(hostname='worker-02', address='192.0.2.22'),
                   dict(hostname='control-01', address='192.0.2.11'),
                   dict(hostname='worker-01', address='192.0.2.21')]
        env = Environment(loader=FileSystemLoader(ROLE / 'templates'))
        text = env.get_template('hosts-block.j2').render(
            baseline_validated_hosts_entries=POLICY.hosts_entries_safe(entries))
        self.assertEqual(text.splitlines(), ['192.0.2.11 control-01',
                                            '192.0.2.21 worker-01', '192.0.2.22 worker-02'])

    def test_ambiguous_and_unsafe_records_are_rejected(self):
        record = dict(hostname='worker-01', address='192.0.2.21')
        for records in [[record, record], [record, dict(hostname='worker-02', address='192.0.2.21')],
                        [dict(hostname='worker-01\nadmin', address='192.0.2.21')],
                        [dict(hostname='worker-01', address='127.0.0.1')],
                        [dict(hostname='worker-01', address='192.0.2.21/24')],
                        [dict(hostname='worker-01', address='192.0.2.21\n127.0.0.1')],
                        [dict(hostname='worker-01')]]:
            with self.subTest(records=records), self.assertRaises(AnsibleFilterError):
                POLICY.hosts_entries_safe(records)

    def test_empty_records_preserve_optional_role_behavior(self):
        self.assertEqual(POLICY.hosts_entries_safe([]), [])


class LogrotateTemplateTests(unittest.TestCase):
    def test_ubuntu_rotation_identity_precedes_package_includes(self):
        env = Environment(loader=FileSystemLoader(ROLE / 'templates'), trim_blocks=True)
        text = env.get_template('logrotate.conf.j2').render(
            baseline_logrotate_frequency='daily', baseline_logrotate_keep=14,
            baseline_logrotate_maxsize='50M')
        directives = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith('#')]
        self.assertIn('su root adm', directives)
        self.assertLess(directives.index('su root adm'), directives.index('include /etc/logrotate.d'))
