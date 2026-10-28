#!/usr/bin/env python3
"""Catch private artifact paths and personal home paths before public commits."""
import fnmatch
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
result = subprocess.run(['git', '-C', str(root), 'ls-files', '--cached', '--others', '--exclude-standard'],
                        check=True, text=True, capture_output=True)
failures = []
for relative in set(result.stdout.splitlines()):
    path = Path(relative)
    lower_parts = [part.lower() for part in path.parts]
    forbidden_name = path.name.lower() in ['agent.md', 'agents.md', 'claude.md', 'memory.md']
    forbidden_directory = any(part in ['memory', 'secrets', 'backups', '.generated', '.agents', '.codex', '.venv', '.local'] for part in lower_parts)
    forbidden_artifact = any(fnmatch.fnmatch(path.name, pattern) for pattern in ['*.tfstate*', '*.tfplan', '*.vdi', '*.vmdk', '*.iso', '*.pem', '*.key'])
    private_vars = path.name.endswith(('.tfvars', '.tfvars.json', '.backend.hcl'))
    if forbidden_name or forbidden_directory or forbidden_artifact or private_vars:
        failures.append(f'Private artifact: {relative}')
        continue
    candidate = root / path
    if candidate.is_file() and candidate.suffix in ['.md', '.json', '.py', '.tf', '.yml', '.yaml', '.sh', '.txt', '.lock']:
        if re.search(r'/(?:Users|home)/[A-Za-z0-9._-]+/', candidate.read_text(errors='replace')):
            failures.append(f'Personal home path: {relative}')
if failures:
    print('\n'.join(sorted(failures)), file=sys.stderr)
    sys.exit(1)
print('Public artifact/privacy checks passed; this is not a complete secret scanner.')
