import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('specctl', ROOT / 'scripts/specctl.py')
specctl = importlib.util.module_from_spec(loader)
loader.loader.exec_module(specctl)


class SpecificationTests(unittest.TestCase):
    def setUp(self):
        self.lab = specctl.load_json(ROOT / 'specs/lab-virtualbox.json')
        self.single = specctl.load_json(ROOT / 'specs/lab-virtualbox-single.json')
        self.prod = specctl.load_json(ROOT / 'specs/production-proxmox.example.json')

    def test_examples_validate_without_claiming_deployment_readiness(self):
        for spec in [self.lab, self.single, self.prod]:
            specctl.validate(spec)
            with self.assertRaisesRegex(ValueError, 'Deployment blocked'):
                specctl.validate(spec, deployment=True)

    def test_single_control_plane_inventory_and_direct_api(self):
        specctl.validate(self.single)
        inv = specctl.inventory(self.single)
        groups = inv['all']['children']
        self.assertEqual(set(groups['kube_control_plane']['hosts']), {'cp1'})
        self.assertEqual(set(groups['etcd']['hosts']), {'cp1'})
        self.assertEqual(set(groups['kube_node']['hosts']), {'worker1', 'worker2'})
        variables = specctl.kubespray_vars(self.single)
        self.assertFalse(variables['kube_vip_enabled'])
        self.assertFalse(variables['kube_vip_services_enabled'])
        self.assertFalse(variables['loadbalancer_apiserver_localhost'])
        self.assertEqual(variables['loadbalancer_apiserver'], {'address': '192.168.56.11', 'port': 6443})
        self.assertIn('192.168.56.11', variables['supplementary_addresses_in_ssl_keys'])

    def test_direct_api_rejects_worker_and_unused_addresses(self):
        for address in ['192.168.56.21', '192.168.56.10']:
            candidate = copy.deepcopy(self.single)
            candidate['network']['api_vip'] = address
            with self.assertRaisesRegex(ValueError, 'Node API endpoint'):
                specctl.validate(candidate)

    def test_direct_api_rejects_ha_and_production(self):
        for spec in [self.lab, self.prod]:
            candidate = copy.deepcopy(spec)
            candidate['components']['api_endpoint'] = 'node'
            candidate['network']['api_vip'] = candidate['nodes']['cp1']['ip']
            with self.assertRaisesRegex(ValueError, 'Node API endpoint'):
                specctl.validate(candidate)
        candidate = copy.deepcopy(self.prod)
        del candidate['nodes']['cp2']
        del candidate['nodes']['cp3']
        with self.assertRaisesRegex(ValueError, 'production requires'):
            specctl.validate(candidate)

    def test_two_control_planes_and_one_worker_remain_rejected(self):
        candidate = copy.deepcopy(self.lab)
        del candidate['nodes']['cp3']
        with self.assertRaises(ValueError):
            specctl.validate(candidate)
        candidate = copy.deepcopy(self.single)
        del candidate['nodes']['worker2']
        with self.assertRaises(ValueError):
            specctl.validate(candidate)

    def test_single_lab_still_rejects_address_collisions(self):
        for mutate in [
            lambda s: s['nodes']['worker1'].update(ip=s['nodes']['cp1']['ip']),
            lambda s: s['network'].update(service_pool_start='192.168.56.11'),
            lambda s: s['network'].update(gateway='192.168.56.11'),
            lambda s: s['components'].update(api_endpoint='external'),
            lambda s: s['components'].update(api_endpoint='kube_vip'),
        ]:
            candidate = copy.deepcopy(self.single)
            mutate(candidate)
            with self.assertRaises(ValueError):
                specctl.validate(candidate)

    def test_external_api_endpoint_can_use_another_routed_network(self):
        self.prod['components']['api_endpoint'] = 'external'
        self.prod['network']['api_vip'] = '192.0.2.10'
        specctl.validate(self.prod)
        self.prod['network']['api_vip'] = '10.244.1.1'
        with self.assertRaisesRegex(ValueError, 'pod or Service'):
            specctl.validate(self.prod)

    def test_typo_is_rejected(self):
        self.lab['nodes']['cp1']['memroy_mib'] = 2048
        with self.assertRaisesRegex(ValueError, 'Additional properties'):
            specctl.validate(self.lab)

    def test_network_collision_cases(self):
        mutations = [
            lambda s: s['network'].update(pod_cidr='192.168.56.0/24'),
            lambda s: s['nodes']['cp2'].update(ip=s['nodes']['cp1']['ip']),
            lambda s: s['network'].update(api_vip=s['nodes']['cp1']['ip']),
            lambda s: s['network'].update(service_pool_start='192.168.56.10'),
            lambda s: s['network'].update(service_pool_end='192.168.56.1'),
            lambda s: s['nodes']['cp1'].update(ip='192.0.2.11'),
            lambda s: s['network'].update(gateway='192.168.56.11'),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                candidate = copy.deepcopy(self.lab)
                mutate(candidate)
                with self.assertRaises(ValueError):
                    specctl.validate(candidate)

    def test_architecture_and_release_bundle_are_checked(self):
        self.lab['image']['architecture'] = 'x86_64'
        with self.assertRaisesRegex(ValueError, 'architectures differ'):
            specctl.validate(self.lab)
        self.lab['image']['architecture'] = 'aarch64'
        self.lab['versions']['kubernetes'] = '1.20.0'
        with self.assertRaisesRegex(ValueError, 'reviewed version bundle'):
            specctl.validate(self.lab)

    def test_production_cannot_relabel_one_host_as_three_domains(self):
        for n in self.prod['nodes'].values():
            n['hypervisor_host'] = 'same-host'
        with self.assertRaisesRegex(ValueError, 'multiple independent failure domains'):
            specctl.validate(self.prod)

    def test_production_requires_network_policy_and_independent_backups(self):
        for key, value in [('cni', 'flannel'), ('gitops', 'none'), ('storage_driver', 'local_path'), ('etcd_mode', 'kubeadm')]:
            candidate = copy.deepcopy(self.prod)
            candidate['components'][key] = value
            with self.assertRaises(ValueError):
                specctl.validate(candidate)
        self.prod['dr']['independent_backup'] = False
        with self.assertRaisesRegex(ValueError, 'independently recoverable'):
            specctl.validate(self.prod)

    def test_no_root_or_internet_wide_management(self):
        self.lab['security']['ssh_user'] = 'root'
        with self.assertRaises(ValueError):
            specctl.validate(self.lab)
        self.lab['security']['ssh_user'] = 'ubuntu'
        self.lab['security']['management_cidrs'] = ['0.0.0.0/0']
        with self.assertRaisesRegex(ValueError, 'entire Internet'):
            specctl.validate(self.lab)

    def facts(self):
        return {'provisioned_nodes': {'value': {
            name: {'id': str(index), 'ip': node['ip'], 'observed_ips': [node['ip']],
                   'hypervisor_host': node['hypervisor_host'], 'image_build_id': self.lab['image']['build_id']}
            for index, (name, node) in enumerate(self.lab['nodes'].items(), 100)
        }}}

    def test_inventory_requires_matching_observations(self):
        facts = self.facts()
        inv = specctl.inventory(self.lab, facts)
        self.assertEqual(len(inv['all']['children']['kube_control_plane']['hosts']), 3)
        self.assertEqual(len(inv['all']['children']['kube_node']['hosts']), 2)
        self.assertEqual(set(inv['all']['children']['etcd']['hosts']), {'cp1', 'cp2', 'cp3'})
        facts['provisioned_nodes']['value']['cp2']['observed_ips'] = []
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            specctl.inventory(self.lab, facts)

    def test_duplicate_and_missing_vm_identity_are_rejected(self):
        facts = self.facts()
        facts['provisioned_nodes']['value']['cp2']['id'] = facts['provisioned_nodes']['value']['cp1']['id']
        with self.assertRaisesRegex(ValueError, 'same VM identity'):
            specctl.inventory(self.lab, facts)
        del facts['provisioned_nodes']['value']['worker2']
        with self.assertRaisesRegex(ValueError, 'exactly match'):
            specctl.inventory(self.lab, facts)

    def test_engine_owns_only_control_plane_vip_and_respects_etcd_mode(self):
        lab = specctl.kubespray_vars(self.lab)
        prod = specctl.kubespray_vars(self.prod)
        self.assertFalse(lab['kube_vip_services_enabled'])
        self.assertFalse(lab['metallb_enabled'])
        self.assertEqual(lab['etcd_deployment_type'], 'kubeadm')
        self.assertEqual(prod['etcd_deployment_type'], 'host')
        self.assertTrue(prod['kube_oidc_auth'])
        self.assertEqual(lab['loadbalancer_apiserver']['address'], self.lab['network']['api_vip'])

    def test_private_outputs_refuse_overwrite_and_use_restrictive_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            out = specctl.private_output(Path(directory) / 'private')
            self.assertEqual(out.stat().st_mode & 0o777, 0o700)
            path = out / 'inventory.json'
            specctl.write_private(path, {'example': True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                specctl.write_private(path, {})
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            with self.assertRaisesRegex(ValueError, 'ignored directory'):
                specctl.private_output(Path(directory))

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'duplicate.json'
            path.write_text('{"name":"a","name":"b"}')
            with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
                specctl.load_json(path)


if __name__ == '__main__':
    unittest.main()
