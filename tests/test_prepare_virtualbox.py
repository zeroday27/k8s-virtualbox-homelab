import sys
from pathlib import Path
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_virtualbox
import specctl


class InstallerPolicyTests(unittest.TestCase):
    def config(self, profile):
        spec = specctl.load_json(ROOT / 'specs' / profile)
        return prepare_virtualbox.seed_config(spec, 'cp1', uuid.uuid4(), 'ssh-ed25519 AAAA synthetic-test-key')[0]['autoinstall']

    def test_lab_preserves_usable_memory_without_a_crash_reservation(self):
        config = self.config('lab-virtualbox-single.json')
        self.assertFalse(config['kernel-crash-dumps']['enabled'])
        self.assertEqual(config['late-commands'][-1][-1], 'update-grub')
        self.assertIn('zz-lab-memory.cfg', config['late-commands'][-2][-1])

    def test_production_seed_does_not_receive_lab_memory_policy(self):
        config = self.config('production-proxmox.example.json')
        self.assertNotIn('kernel-crash-dumps', config)
        self.assertFalse(any('zz-lab-memory.cfg' in str(command) for command in config['late-commands']))
