"""Exercise CSR approval boundaries, certificate renewal and add-on trust."""
import base64
import copy
import importlib.util
import ipaddress
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from ansible.errors import AnsibleFilterError
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec
from cryptography.x509.oid import NameOID
from jinja2 import Environment, FileSystemLoader
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'ansible/roles/metrics_server'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLICY = load('serving_csr', ROLE / 'filter_plugins/serving_csr.py')
CERTIFICATE = load('serving_certificate', ROLE / 'files/serving_certificate.py')


class ServingApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def request(self, dns=None, ips=None, subject=None, extra_extension=False, key=None):
        subject = subject or x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'system:nodes'),
                                      x509.NameAttribute(NameOID.COMMON_NAME, 'system:node:worker-example')])
        sans = [x509.DNSName(n) for n in (dns if dns is not None else ['worker-example'])]
        sans += [x509.IPAddress(ipaddress.ip_address(n)) for n in (ips if ips is not None else ['192.0.2.21'])]
        builder = x509.CertificateSigningRequestBuilder().subject_name(subject).add_extension(x509.SubjectAlternativeName(sans), False)
        if extra_extension:
            builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        csr = builder.sign(key or self.key, hashes.SHA256())
        return {'apiVersion': 'certificates.k8s.io/v1', 'kind': 'CertificateSigningRequest',
                'metadata': {'name': 'csr-example123', 'uid': 'test-uid', 'resourceVersion': '7'},
                'spec': {'signerName': 'kubernetes.io/kubelet-serving', 'username': 'system:node:worker-example',
                         'groups': ['system:nodes', 'system:authenticated'],
                         'usages': ['digital signature', 'key encipherment', 'server auth'],
                         'request': base64.b64encode(csr.public_bytes(serialization.Encoding.PEM)).decode()}}

    def approve(self, request):
        return POLICY.serving_approval(request, 'worker-example', '192.0.2.21')

    def test_inventory_request_gets_version_bound_approval_without_mutation(self):
        request = self.request()
        before = copy.deepcopy(request)
        approval = self.approve(request)
        self.assertEqual(request, before)
        self.assertEqual(approval['metadata']['uid'], 'test-uid')
        self.assertEqual(approval['metadata']['resourceVersion'], '7')
        self.assertEqual(approval['status']['conditions'][0]['type'], 'Approved')

    def test_ecdsa_serving_request_without_key_encipherment_is_supported(self):
        request = self.request(key=ec.generate_private_key(ec.SECP256R1()))
        request['spec']['usages'] = ['digital signature', 'server auth']
        self.assertEqual(self.approve(request)['status']['conditions'][0]['type'], 'Approved')
        for usages in [['server auth'], ['digital signature'], ['digital signature', 'server auth', 'client auth']]:
            request['spec']['usages'] = usages
            with self.subTest(usages=usages), self.assertRaises(AnsibleFilterError):
                self.approve(request)

    def test_foreign_sans_and_ca_extensions_are_rejected(self):
        for request in [self.request(ips=['192.0.2.11']), self.request(dns=['worker-example', 'control-example']),
                        self.request(dns=['*.example']), self.request(ips=['192.0.2.21', '127.0.0.1']),
                        self.request(extra_extension=True)]:
            with self.assertRaises(AnsibleFilterError):
                self.approve(request)

    def test_authenticated_identity_groups_signer_and_usages_are_required(self):
        for key, value in [('username', 'system:node:other'), ('groups', ['system:masters']),
                           ('signerName', 'kubernetes.io/kube-apiserver-client-kubelet'), ('usages', ['client auth'])]:
            request = self.request()
            request['spec'][key] = value
            with self.subTest(key=key), self.assertRaises(AnsibleFilterError):
                self.approve(request)

    def test_subject_escalation_and_existing_decisions_are_rejected(self):
        request = self.request(subject=x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'system:masters'),
                                                 x509.NameAttribute(NameOID.COMMON_NAME, 'system:node:worker-example')]))
        with self.assertRaises(AnsibleFilterError):
            self.approve(request)
        for status in [{'conditions': [{'type': 'Denied'}]}, {'conditions': [{'type': 'Approved'}]}, {'certificate': 'issued'}]:
            request = self.request()
            request['status'] = status
            with self.assertRaises(AnsibleFilterError):
                self.approve(request)

    def test_tampered_signature_and_unversioned_resources_are_rejected(self):
        request = self.request()
        csr = x509.load_pem_x509_csr(base64.b64decode(request['spec']['request']))
        der = bytearray(csr.public_bytes(serialization.Encoding.DER))
        der[-1] ^= 1
        tampered = x509.load_der_x509_csr(bytes(der))
        request['spec']['request'] = base64.b64encode(tampered.public_bytes(serialization.Encoding.PEM)).decode()
        with self.assertRaises(AnsibleFilterError):
            self.approve(request)
        request = self.request()
        request['metadata'].pop('resourceVersion')
        with self.assertRaises(AnsibleFilterError):
            self.approve(request)


class MetricsCertificateTests(unittest.TestCase):
    def test_local_ca_certificate_is_valid_private_idempotent_and_renewable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ca, key = root / 'ca.crt', root / 'ca.key'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
                            '-out', str(ca), '-days', '365', '-subj', '/CN=TestCA',
                            '-addext', 'basicConstraints=critical,CA:TRUE'], check=True, capture_output=True)
            names = ['metrics-server.kube-system.svc', 'metrics-server.kube-system.svc.cluster.local']
            first = CERTIFICATE.reconcile(root / 'tls', str(ca), str(key), names)
            self.assertTrue(first['changed'])
            self.assertEqual((root / 'tls/tls.key').stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / 'tls').stat().st_mode & 0o777, 0o700)
            self.assertFalse(CERTIFICATE.reconcile(root / 'tls', str(ca), str(key), names)['changed'])
            renewed = CERTIFICATE.reconcile(root / 'tls', str(ca), str(key), names, renew_days=100)
            self.assertTrue(renewed['changed'])
            self.assertNotEqual(first['certificate_sha256'], renewed['certificate_sha256'])
            self.assertEqual(sorted(p.name for p in (root / 'tls').iterdir()), ['tls.crt', 'tls.key'])
            subprocess.run(['openssl', 'verify', '-CAfile', str(ca), '-purpose', 'sslserver',
                            str(root / 'tls/tls.crt')], check=True, capture_output=True)
            certificate = x509.load_pem_x509_certificate((root / 'tls/tls.crt').read_bytes())
            self.assertEqual(certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName), names)
            self.assertFalse(certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)

    def test_manifest_overlay_requires_tls_verification_and_digest_images(self):
        bom = json.loads((ROOT / 'ansible/vars/k8s-components.bom.json').read_text())['metrics_server_bom']
        env = Environment(loader=FileSystemLoader(ROLE / 'templates'), trim_blocks=True, lstrip_blocks=True)
        env.filters['to_json'] = json.dumps
        overlay = yaml.safe_load(env.get_template('kustomization.yml.j2').render(metrics_server_bom=bom,
            metrics_server_replicas=1, metrics_server_certificate_sha256='a' * 64, metrics_server_cpu_request='100m',
            metrics_server_memory_request='200Mi', metrics_server_ca_bundle='Y2E='))
        self.assertRegex(overlay['images'][0]['digest'], '^sha256:[a-f0-9]{64}$')
        self.assertEqual(set(bom['image']['architectures']), {'arm64', 'amd64'})
        deployment, api = [yaml.safe_load(p['patch']) for p in overlay['patches']]
        args = deployment['spec']['template']['spec']['containers'][0]['args']
        self.assertFalse(any('insecure' in flag for flag in args))
        self.assertIn('--kubelet-certificate-authority=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt', args)
        self.assertFalse(api['spec']['insecureSkipTLSVerify'])
        self.assertEqual(api['spec']['caBundle'], 'Y2E=')
        self.assertEqual(deployment['spec']['template']['spec']['volumes'][0]['secret']['defaultMode'], 0o440)

    def test_tagged_addon_phases_preserve_serial_node_preparation(self):
        plays = yaml.safe_load((ROOT / 'ansible/playbooks/05-k8s-components.yml').read_text())
        self.assertEqual([p['hosts'] for p in plays], ['control_plane', 'lab_nodes', 'control_plane'])
        self.assertEqual(plays[1]['serial'], 1)
        for play in plays:
            task = play['tasks'][0]
            self.assertEqual(task['tags'], ['metrics_server'])
            self.assertEqual(task['ansible.builtin.include_role']['apply']['tags'], ['metrics_server'])
        node = (ROLE / 'tasks/node.yml').read_text()
        self.assertIn('tasks_from: firewall.yml', node)
        self.assertNotIn('tasks_from: main.yml', node)
        self.assertIn('when: not ansible_check_mode', node)
