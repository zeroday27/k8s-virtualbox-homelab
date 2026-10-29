"""Bootstrap rendering and destructive/credential boundaries."""
import json
from pathlib import Path
import unittest
from jinja2 import Environment, FileSystemLoader
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'ansible/roles/k8s_base'
BOM = json.loads((ROOT / 'ansible/vars/k8s-base.bom.json').read_text())['k8s_base_bom']


def render(name, **updates):
    env = Environment(loader=FileSystemLoader(ROLE / 'templates'))
    env.filters['to_json'] = json.dumps
    context = dict(k8s_base_bom=BOM, k8s_base_policy={'node_ip': '192.0.2.11'},
                   inventory_hostname='control-example', k8s_base_cri_socket='unix:///run/containerd/containerd.sock',
                   k8s_base_bootstrap_dir='/var/lib/k8s-base/bootstrap', k8s_base_cluster_name='vanilla-lab',
                   k8s_base_pod_cidr='10.244.0.0/16', k8s_base_service_cidr='10.96.0.0/12', k8s_base_dns_domain='cluster.local',
                   groups={'control_plane': ['control-example']},
                   hostvars={'control-example': {'k8s_base_policy': {'node_ip': '192.0.2.11'}}},
                   k8s_base_join_token={'stdout': 'abcdef.0123456789abcdef'}, k8s_base_ca_hash={'stdout': 'a' * 64})
    context.update(updates)
    return list(yaml.safe_load_all(env.get_template(name).render(**context)))


class BootstrapTests(unittest.TestCase):
    def test_init_uses_static_management_ip_and_digest_pins(self):
        init, cluster, kubelet = render('kubeadm-init.yml.j2')
        self.assertEqual(init['bootstrapTokens'], [])
        self.assertEqual(init['localAPIEndpoint']['advertiseAddress'], '192.0.2.11')
        self.assertEqual(init['nodeRegistration']['criSocket'], 'unix:///run/containerd/containerd.sock')
        self.assertEqual(cluster['controlPlaneEndpoint'], '192.0.2.11:6443')
        self.assertEqual(cluster['etcd']['local']['imageTag'], BOM['bootstrap_images']['etcd'].split(':', 1)[1])
        self.assertEqual(cluster['dns']['imageTag'], BOM['bootstrap_images']['coredns'].split(':', 1)[1])
        self.assertEqual(kubelet['cgroupDriver'], 'systemd')
        self.assertFalse(kubelet['authentication']['anonymous']['enabled'])
        self.assertEqual(kubelet['authorization']['mode'], 'Webhook')
        self.assertEqual(kubelet['readOnlyPort'], 0)

    def test_join_requires_token_and_trusted_ca_without_unsafe_discovery(self):
        join, = render('kubeadm-join.yml.j2', inventory_hostname='worker-example',
                       k8s_base_policy={'node_ip': '192.0.2.21'})
        discovery = join['discovery']['bootstrapToken']
        self.assertEqual(discovery['apiServerEndpoint'], '192.0.2.11:6443')
        self.assertEqual(discovery['caCertHashes'], ['sha256:' + 'a' * 64])
        self.assertNotIn('unsafeSkipCAVerification', discovery)
        self.assertEqual(join['nodeRegistration']['kubeletExtraArgs'][0]['value'], '192.0.2.21')

    def test_join_hides_credentials_and_always_cleans_up(self):
        tasks = yaml.safe_load((ROLE / 'tasks/join.yml').read_text())
        block = next(t for t in tasks if 'always' in t)
        names = [t['name'] for t in block['always']]
        self.assertTrue(any('Remove' in n for n in names))
        self.assertTrue(any('Revoke' in n for n in names))
        for task in block['block'] + block['always']:
            if any(word in task['name'] for word in ['token', 'private join', 'Join the worker']):
                self.assertTrue(task.get('no_log'), task['name'])
        self.assertIn('not ansible_check_mode', block['when'])

    def test_phase_order_and_no_reset_or_automatic_calico(self):
        plays = yaml.safe_load((ROOT / 'ansible/playbooks/02-k8s-bootstrap.yml').read_text())
        self.assertEqual([p['hosts'] for p in plays], ['lab_nodes', 'control_plane', 'workers'])
        self.assertEqual(plays[-1]['serial'], 1)
        self.assertTrue(all(p['any_errors_fatal'] for p in plays))
        commands = '\n'.join(p.read_text() for p in (ROLE / 'tasks').glob('*.yml'))
        self.assertNotIn('ignore-preflight-errors', commands)
        self.assertNotIn('unsafe-skip-ca-verification', commands)
        self.assertNotIn('argv: [/usr/local/bin/kubeadm, reset', commands)
        self.assertNotIn('03-k8s-calico.yml', (ROOT / 'ansible/playbooks/02-k8s-bootstrap.yml').read_text())
