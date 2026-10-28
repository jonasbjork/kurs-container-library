#!/usr/bin/env python3
"""Install checksum-pinned official binaries; no curl|shell installers."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import tarfile
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dest', type=Path, required=True)
    parser.add_argument('--lock', choices=['tools.lock.json', 'okd-client.lock.json'], default='tools.lock.json')
    args = parser.parse_args()
    machine = {'x86_64': 'amd64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(platform.machine())
    target = f'{platform.system().lower()}/{machine}'
    lock = json.loads((ROOT / args.lock).read_text())
    args.dest.mkdir(parents=True, exist_ok=True)
    for name, tool in lock.items():
        asset = tool['assets'][target]
        prefix = (f'https://mirror.openshift.com/pub/openshift-v4/x86_64/clients/ocp/{tool["version"]}/'
                  if name == 'oc' and args.lock == 'okd-client.lock.json'
                  else f'https://github.com/{tool["repository"]}/releases/download/')
        if not asset['url'].startswith(prefix):
            raise ValueError('tool download must use its official versioned distribution')
        downloads = args.dest / '.downloads'
        downloads.mkdir(exist_ok=True)
        archive_path = downloads / (name + '-' + tool['version'] + '.tar.gz')
        if not archive_path.is_file() or hashlib.sha256(archive_path.read_bytes()).hexdigest() != asset['sha256']:
            subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--connect-timeout', '20',
                            '--max-time', '600', '--output', str(archive_path), asset['url']],
                           check=True, timeout=1300)
        data = archive_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != asset['sha256']:
            raise ValueError(f'{name}: download checksum mismatch')
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            # Extract only the named executable, never paths from the archive.
            member = archive.getmember(name)
            if not member.isfile():
                raise ValueError('tool archive must contain a regular executable')
            output = args.dest / name
            output.write_bytes(archive.extractfile(member).read())
            os.chmod(output, 0o755)
        print(f'{name} {tool["version"]}: {output}')


if __name__ == '__main__':
    main()
