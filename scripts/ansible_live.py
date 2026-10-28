#!/usr/bin/env python3
"""Stream Ansible output to the terminal and a private log, preserving its exit code."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from specctl import private_output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or Path(command[0]).name != 'ansible-playbook':
        parser.error('Provide an ansible-playbook command after --')
    private_output(args.log.parent)
    descriptor = os.open(args.log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    env['ANSIBLE_NOCOLOR'] = '1'
    env['ANSIBLE_HOST_KEY_CHECKING'] = 'True'
    with os.fdopen(descriptor, 'w', buffering=1) as log:
        print('Ansible output is streamed below; private log enabled.', flush=True)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1, env=env)
        try:
            for line in process.stdout:
                print(line, end='', flush=True)
                log.write(line)
            result = process.wait()
        except KeyboardInterrupt:
            process.send_signal(__import__('signal').SIGINT)
            result = process.wait()
        print(f'Ansible exited with status {result}.', flush=True)
        return result


if __name__ == '__main__':
    sys.exit(main())
