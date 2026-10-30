#!/usr/bin/env python3
"""Reconcile the owned serving Secret and rollout without logging secret data."""
import argparse
import base64
import fcntl
import json
from pathlib import Path
import subprocess

from serving_certificate import reconcile


ANNOTATION = 'lab.k8s.local/serving-certificate-sha256'


def kubectl(config, args, stdin=None):
    result = subprocess.run(['/usr/local/bin/kubectl', '--kubeconfig=' + config['kubeconfig'],
                             '--request-timeout=30s'] + args, input=stdin, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Kubernetes operation failed with exit status ' + str(result.returncode))
    return result.stdout


def reconcile_component(config, prepare_only=False, client=kubectl):
    state = Path(config['state_dir'])
    if not (state / 'managed').is_file():
        raise ValueError('Role ownership marker is required')
    with (state / 'renewal.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        namespace = ['-n', 'kube-system']
        certificate = reconcile(state / 'tls', config['ca_cert'], config['ca_key'], config['dns_names'],
                                days=config['days'], renew_days=config['renew_days'])
        secret = json.loads(client(config, namespace + ['get', 'secret', 'metrics-server-serving',
                                                       '--ignore-not-found', '-o', 'json']) or '{}')
        expected = {'tls.crt': base64.b64encode((state / 'tls/tls.crt').read_bytes()).decode(),
                    'tls.key': base64.b64encode((state / 'tls/tls.key').read_bytes()).decode()}
        secret_changed = secret.get('data') != expected or secret.get('type') != 'kubernetes.io/tls'
        if secret_changed:
            payload = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'kubernetes.io/tls',
                       'metadata': {'name': 'metrics-server-serving', 'namespace': 'kube-system'}, 'data': expected}
            client(config, ['apply', '--server-side', '--field-manager=k8s-components', '-f', '-'], json.dumps(payload))
        deployment_changed = False
        if not prepare_only:
            deployment = json.loads(client(config, namespace + ['get', 'deployment', 'metrics-server', '-o', 'json']))
            annotations = deployment['spec']['template']['metadata'].get('annotations', {})
            deployment_changed = annotations.get(ANNOTATION) != certificate['certificate_sha256']
            if deployment_changed:
                patch = {'spec': {'template': {'metadata': {'annotations': {ANNOTATION: certificate['certificate_sha256']}}}}}
                client(config, namespace + ['patch', 'deployment', 'metrics-server', '--type=merge',
                                           '--field-manager=k8s-components', '-p', json.dumps(patch)])
            client(config, namespace + ['rollout', 'status', 'deployment/metrics-server', '--timeout=300s'])
            client(config, ['wait', '--for=condition=Available', 'apiservice/v1beta1.metrics.k8s.io', '--timeout=300s'])
        return {'changed': certificate['changed'] or secret_changed or deployment_changed,
                'certificate_changed': certificate['changed'], 'secret_changed': secret_changed,
                'deployment_changed': deployment_changed, 'certificate_sha256': certificate['certificate_sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--prepare-only', action='store_true')
    options = parser.parse_args()
    try:
        print(json.dumps(reconcile_component(json.loads(Path(options.config).read_text()), options.prepare_only)))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, 'Metrics Server renewal failed: ' + type(error).__name__ + '\n')
