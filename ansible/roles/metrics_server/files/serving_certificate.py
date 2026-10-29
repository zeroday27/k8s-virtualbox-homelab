#!/usr/bin/env python3
"""Issue/renew one role-owned serving certificate locally without exporting CA keys."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile


def run(args, check=True):
    return subprocess.run(['openssl'] + args, check=check, capture_output=True)


def reconcile(directory, ca_cert, ca_key, dns_names, days=90, renew_days=30):
    if not dns_names or any(not re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*', name) for name in dns_names):
        raise ValueError('Explicit service DNS names are required')
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    cert, key = directory / 'tls.crt', directory / 'tls.key'
    valid = cert.is_file() and key.is_file()
    if valid:
        valid = run(['x509', '-in', str(cert), '-checkend', str(renew_days * 86400), '-noout'], False).returncode == 0
        valid = valid and run(['verify', '-CAfile', ca_cert, '-purpose', 'sslserver', str(cert)], False).returncode == 0
        if valid:
            text = run(['x509', '-in', str(cert), '-noout', '-text']).stdout.decode()
            match = re.search(r'X509v3 Subject Alternative Name:[^\n]*\n\s*([^\n]+)', text)
            valid = bool(match) and sorted(part.strip() for part in match[1].split(',')) == sorted('DNS:' + name for name in dns_names)
        if valid:
            public_cert = run(['x509', '-in', str(cert), '-pubkey', '-noout']).stdout
            public_key = run(['pkey', '-in', str(key), '-pubout']).stdout
            valid = public_cert == public_key
    if not valid:
        with tempfile.TemporaryDirectory(prefix='issue-', dir=directory) as temporary:
            stage = Path(temporary)
            old_umask = os.umask(0o077)
            try:
                (stage / 'extensions.cnf').write_text(
                    '[server]\nsubjectAltName=' + ','.join('DNS:' + name for name in dns_names) +
                    '\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n'
                    'extendedKeyUsage=serverAuth\n')
                run(['req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(stage / 'key.pem'),
                     '-out', str(stage / 'request.pem'), '-subj', '/CN=' + dns_names[0]])
                run(['x509', '-req', '-in', str(stage / 'request.pem'), '-CA', ca_cert, '-CAkey', ca_key,
                     '-set_serial', '0x' + format(secrets.randbits(159) or 1, 'x'), '-days', str(days),
                     '-sha256', '-extfile', str(stage / 'extensions.cnf'), '-extensions', 'server', '-out', str(stage / 'cert.pem')])
                os.replace(stage / 'key.pem', key)
                os.replace(stage / 'cert.pem', cert)
            finally:
                os.umask(old_umask)
    os.chmod(key, 0o600)
    os.chmod(cert, 0o644)
    return dict(changed=not valid, certificate_sha256=hashlib.sha256(cert.read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    parser.add_argument('--ca-cert', required=True)
    parser.add_argument('--ca-key', required=True)
    parser.add_argument('--dns-name', action='append', required=True)
    parser.add_argument('--days', type=int, default=90)
    parser.add_argument('--renew-days', type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.directory, args.ca_cert, args.ca_key, args.dns_name, args.days, args.renew_days)))
