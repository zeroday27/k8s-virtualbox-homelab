"""Safety contracts and rendered configuration for the vanilla base profile."""
import importlib.util
import json
from pathlib import Path
import tomllib
import unittest

from ansible.errors import AnsibleFilterError
from jinja2 import Environment, FileSystemLoader
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'ansible/roles/k8s_base'
BOM = json.loads((ROOT / 'ansible/vars/k8s-base.bom.json').read_text())['k8s_base_bom']
SPEC = importlib.util.spec_from_file_location('network_policy', ROLE / 'filter_plugins/network_policy.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class KubernetesBaseTests(unittest.TestCase):
    def settings(self, **updates):
        return dict(node_ip='192.0.2.11', pod_cidr='10.244.0.0/16',
                    service_cidr='10.96.0.0/12', interface='lab0', transport='ipip', **updates)

    def render(self, name):
        env = Environment(loader=FileSystemLoader(ROLE / 'templates'), trim_blocks=True, lstrip_blocks=True)
        return env.get_template(name).render(k8s_base_bom=BOM, k8s_base_node_interface='lab0',
                                             k8s_base_pod_cidr='10.244.0.0/16')

    def test_network_valid(self):
        self.assertEqual(MODULE.network_policy(self.settings())['node_ip'], '192.0.2.11')

    def test_network_rejects_unsafe_inputs(self):
        for key, value in [('node_ip', '127.0.0.1'), ('pod_cidr', '10.96.0.0/16'),
                           ('service_cidr', '192.0.2.0/24'), ('interface', 'lab0;command'),
                           ('transport', 'vxlan'), ('pod_cidr', '::/64')]:
            with self.subTest(key=key, value=value), self.assertRaises(AnsibleFilterError):
                settings = self.settings()
                settings[key] = value
                MODULE.network_policy(settings)

    def test_containerd_criv1_systemd_and_immutable_sandbox(self):
        config = tomllib.loads(self.render('containerd.toml.j2'))
        self.assertEqual(config['version'], 3)
        self.assertTrue(config['plugins']['io.containerd.cri.v1.runtime']['containerd']['runtimes']['runc']['options']['SystemdCgroup'])
        self.assertEqual(config['plugins']['io.containerd.cri.v1.images']['pinned_images']['sandbox'].split('@')[1],
                         BOM['images']['registry.k8s.io/pause']['digest'])

    def test_admin_scope_and_artifact_integrity(self):
        artifacts = {a['name']: a for a in BOM['artifacts_by_arch']['arm64']}
        self.assertEqual(set(artifacts), {'containerd', 'runc', 'crictl', 'kubeadm', 'kubelet', 'kubectl', 'kustomize'})
        self.assertEqual({a['name'] for a in artifacts.values() if a['scope'] == 'control_plane'}, {'kubectl', 'kustomize'})
        for artifact in artifacts.values():
            self.assertRegex(artifact['sha256'], r'^[0-9a-f]{64}$')
            for file in artifact['files']:
                self.assertTrue(file['dest'].startswith(('/usr/local/bin/', '/usr/local/sbin/')))
                self.assertNotIn('..', file['source'])

    def test_calico_overlay_covers_all_images_and_network(self):
        overlay = yaml.safe_load(self.render('calico-kustomization.yml.j2'))
        self.assertEqual({i['name'] for i in overlay['images']},
                         {'quay.io/calico/node', 'quay.io/calico/calico', 'quay.io/calico/third-party-cni-plugins'})
        for image in overlay['images']:
            self.assertRegex(image['digest'], r'^sha256:[0-9a-f]{64}$')
        patch = yaml.safe_load(overlay['patches'][0]['patch'])
        env = {i['name']: i['value'] for i in patch['spec']['template']['spec']['containers'][0]['env']}
        self.assertEqual(env['IP_AUTODETECTION_METHOD'], 'kubernetes-internal-ip')
        self.assertEqual(env['CALICO_IPV4POOL_IPIP'], 'Always')
        self.assertEqual(env['CALICO_IPV4POOL_VXLAN'], 'Never')
        self.assertEqual(env['CALICO_IPV4POOL_CIDR'], '10.244.0.0/16')

    def test_base_does_not_bootstrap_or_apply_calico(self):
        play = yaml.safe_load((ROOT / 'ansible/playbooks/01-k8s-base.yml').read_text())[0]
        self.assertEqual(play['serial'], 1)
        self.assertTrue(play['any_errors_fatal'])
        defaults = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
        self.assertFalse(defaults['k8s_base_calico_apply'])
        service = (ROLE / 'templates/kubelet.service.j2').read_text()
        self.assertLess(service.index('StartLimitIntervalSec'), service.index('[Service]'))

    def test_both_architectures_have_complete_distinct_artifact_locks(self):
        for fact, arch in [('aarch64', 'arm64'), ('x86_64', 'amd64')]:
            self.assertEqual(MODULE.architecture(fact), arch)
            artifacts = MODULE.artifact_contract(BOM, arch)
            self.assertEqual(len(artifacts), 7)
            for artifact in artifacts:
                self.assertIn(arch, artifact['url'])
        self.assertNotEqual(BOM['artifacts_by_arch']['arm64'][0]['sha256'],
                            BOM['artifacts_by_arch']['amd64'][0]['sha256'])
        with self.assertRaises(AnsibleFilterError):
            MODULE.architecture('i686')

    def test_artifact_contract_rejects_wrong_cpu_scope_and_lock(self):
        import copy
        for key, value in [('url', 'https://example.invalid/linux-amd64'),
                           ('sha256', 'unlocked'), ('scope', 'control_plane'), ('version', 'latest')]:
            broken = copy.deepcopy(BOM)
            broken['artifacts_by_arch']['arm64'][0][key] = value
            with self.subTest(key=key), self.assertRaises(AnsibleFilterError):
                MODULE.artifact_contract(broken, 'arm64')

    def test_all_image_indexes_have_both_cpu_manifests(self):
        for image in BOM['images'].values():
            self.assertEqual(set(image['architectures']), {'arm64', 'amd64'})
            self.assertRegex(image['digest'], r'^sha256:[a-f0-9]{64}$')
            for digest in image['architectures'].values():
                self.assertRegex(digest, r'^sha256:[a-f0-9]{64}$')
        for component in ['etcd', 'coredns', 'pause']:
            self.assertIn('@sha256:', BOM['bootstrap_images'][component])
