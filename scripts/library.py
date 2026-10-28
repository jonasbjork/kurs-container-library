#!/usr/bin/env python3
"""Manifest-driven Linux/amd64 build, smoke test and guarded publication."""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def run(*args, capture=False):
    print('+', ' '.join(map(str, args)), flush=True)
    result = subprocess.run([str(a) for a in args], cwd=ROOT, check=True,
                            text=True, capture_output=capture, timeout=1800)
    return result.stdout.strip() if capture else None


def load_manifest():
    cfg = yaml.safe_load((ROOT / 'images.yaml').read_text())
    if not isinstance(cfg, dict) or cfg.get('namespace') != 'quay.io/kurs':
        raise ValueError('namespace must be quay.io/kurs')
    items = cfg.get('images')
    if not isinstance(items, list) or not items:
        raise ValueError('images must be a nonempty list')
    names = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('each image must be a mapping')
        name = item.get('name', '')
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or name in names:
            raise ValueError('invalid or duplicate image name')
        names.add(name)
        if item.get('strategy') != 'build' or item.get('test') not in ('http', 'postgres', 'python', 'tools', 'mysql', 'mariadb', 'wordpress', 'phpmyadmin'):
            raise ValueError(f'{name}: unsupported strategy or test')
        if not isinstance(item.get('version'), str) or not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}', item['version']):
            raise ValueError(f'{name}: invalid version')
        if not isinstance(item.get('context'), str):
            raise ValueError(f'{name}: context must be a string')
        context = (ROOT / item['context']).resolve()
        if ROOT not in context.parents or not (context / 'Containerfile').is_file():
            raise ValueError(f'{name}: invalid build context')
        if not isinstance(item.get('port', 8080), int) or not 1024 <= item.get('port', 8080) <= 65535:
            raise ValueError(f'{name}: invalid port')
        if not isinstance(item.get('path', '/'), str) or not item.get('path', '/').startswith('/'):
            raise ValueError(f'{name}: invalid HTTP path')
    return cfg


def test_image(item, image):
    run(sys.executable, 'scripts/smoke.py', '--image', image, '--type', item['test'],
        '--port', str(item.get('port', 8080)), '--path', item.get('path', '/'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('action', choices=['list', 'build', 'test', 'publish'])
    ap.add_argument('--name', default='all')
    ap.add_argument('--channel', choices=['candidate', 'stable'], default='candidate')
    ap.add_argument('--run-id', default=f"{os.getenv('GITHUB_RUN_ID', 'local')}-{os.getenv('GITHUB_RUN_ATTEMPT', '1')}")
    a = ap.parse_args()
    cfg = load_manifest()
    selected = [i for i in cfg['images'] if a.name in ('all', i['name'])]
    if not selected:
        ap.error('unknown image name')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', a.run_id):
        ap.error('invalid run id')
    if a.action == 'publish':
        if os.environ.get('ALLOW_PUBLISH') != 'yes':
            ap.error('Publication disabled; explicit ALLOW_PUBLISH=yes required')
        if a.channel == 'stable':
            ap.error('Stable publication disabled until registry-enforced tag immutability is configured and verified')
        # Resolve immutable local IDs, then test ALL selected images before any push.
        tested = []
        for item in selected:
            image = run('podman', 'image', 'inspect', '--format', '{{.Id}}', f"localhost/kurs/{item['name']}:test", capture=True)
            test_image(item, image)
            tested.append((item, image))
        for item, image in tested:
            run('podman', 'push', image, f"docker://{cfg['namespace']}/{item['name']}:candidate-{a.run_id}")
        return
    for item in selected:
        local = f"localhost/kurs/{item['name']}:test"
        if a.action == 'list':
            tag = f'candidate-{a.run_id}' if a.channel == 'candidate' else item['version']
            print(f"{item['name']:18} {item['strategy']:8} {cfg['namespace']}/{item['name']}:{tag}")
        elif a.action == 'build':
            run('podman', 'build', '--platform=linux/amd64', '--pull=always', '-f',
                f"{item['context']}/Containerfile", '-t', local, item['context'])
        else:
            test_image(item, local)


if __name__ == '__main__':
    main()
