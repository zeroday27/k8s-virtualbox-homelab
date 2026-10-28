from pathlib import Path
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_virtualbox_clone as clone
import specctl


class CloneSeedTests(unittest.TestCase):
    def setUp(self):
        self.spec = specctl.load_json(ROOT / 'specs/lab-virtualbox-single.json')
        self.key = 'ssh-ed25519 AAAA synthetic-key'

    def test_clones_receive_distinct_identity_and_per_nic_macs(self):
        first = clone.clone_seed(self.spec, 'worker1', str(uuid.uuid4()), self.key)
        second = clone.clone_seed(self.spec, 'worker2', str(uuid.uuid4()), self.key)
        self.assertNotEqual(first['meta-data']['instance-id'], second['meta-data']['instance-id'])
        macs = [item['identity'][nic] for item in [first, second] for nic in ['nat_mac', 'lab_mac']]
        self.assertEqual(len(set(macs)), 4)
        self.assertEqual(first['network-config']['ethernets']['lab0']['addresses'], ['192.168.56.21/24'])
        self.assertTrue(first['user-data']['ssh_deletekeys'])
        self.assertFalse(first['user-data']['ssh_pwauth'])
        self.assertNotIn('autoinstall', first['user-data'])

    def test_unsupported_platform_bad_identity_and_key_are_rejected(self):
        prod = specctl.load_json(ROOT / 'specs/production-proxmox.example.json')
        for spec, node, identity, key in [
            (prod, 'cp1', str(uuid.uuid4()), self.key),
            (self.spec, 'unknown', str(uuid.uuid4()), self.key),
            (self.spec, 'worker1', 'not-a-uuid', self.key),
            (self.spec, 'worker1', str(uuid.uuid4()), 'not-a-public-key'),
        ]:
            with self.assertRaises(ValueError):
                clone.clone_seed(spec, node, identity, key)

    def test_private_seed_files_do_not_overwrite_and_are_restricted(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'seed'
            clone.prepare(self.spec, 'worker1', str(uuid.uuid4()), self.key, output)
            for name in ['user-data', 'meta-data', 'network-config', 'identity.json']:
                self.assertEqual((output / name).stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                clone.prepare(self.spec, 'worker1', str(uuid.uuid4()), self.key, output)
