from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from generalize_virtualbox_guest import bootstrap_state


class GeneralizationBootstrapTests(unittest.TestCase):
    def status(self):
        return {'status': 'disabled', 'errors': [], 'modules-final': {'finished': 9.0, 'errors': []},
                'recoverable_errors': {'WARNING': ["Not unlocking blank password for existing user ubuntu. no existing password set"]}}

    def test_completed_installer_bootstrap_is_classified_explicitly(self):
        self.assertEqual(bootstrap_state(self.status(), 'ubuntu', True), 'installer-disabled-after-completed-bootstrap')
        self.assertEqual(bootstrap_state({'status': 'done', 'errors': []}, 'ubuntu', False), 'done')

    def test_arbitrary_disabled_and_incomplete_bootstraps_are_rejected(self):
        with self.assertRaises(ValueError):
            bootstrap_state(self.status(), 'ubuntu', False)
        status = self.status(); status['modules-final']['finished'] = 0
        with self.assertRaises(ValueError):
            bootstrap_state(status, 'ubuntu', True)

    def test_other_warnings_and_nested_errors_are_rejected(self):
        status = self.status(); status['recoverable_errors']['WARNING'] = ['Network configuration failed']
        with self.assertRaises(ValueError):
            bootstrap_state(status, 'ubuntu', True)
        status = self.status(); status['init'] = {'errors': ['failed']}
        with self.assertRaises(ValueError):
            bootstrap_state(status, 'ubuntu', True)
