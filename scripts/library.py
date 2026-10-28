#!/usr/bin/env python3
"""Manifest-driven, digest-locked build/mirror, verification and publication."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports'


def run(*args, capture=False, binary=False, env=None):
    print('+', ' '.join(map(str, args)), flush=True)
    result = subprocess.run([str(a) for a in args], cwd=ROOT, check=True,
                            text=not binary, capture_output=capture, timeout=1800, env=env)
    return result.stdout if capture else None


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def project_path(value):
    path = (ROOT / value).resolve()
    if Path(value).is_absolute() or ROOT not in path.parents:
        raise ValueError(f'path must be inside the repository: {value}')
    return path


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f'duplicate YAML key: {key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_manifest():
    text = (ROOT / 'images.yaml').read_text()
    yaml.load(text, Loader=UniqueLoader)  # Detect duplicate keys before normal safe parsing.
    cfg = yaml.safe_load(text)
    schema = json.loads((ROOT / 'schema/images.schema.json').read_text())
    try:
        jsonschema.Draft202012Validator(schema).validate(cfg)
    except jsonschema.ValidationError as exc:
        raise ValueError(f'manifest {list(exc.path)}: {exc.message}') from exc
    names = set()
    for item in cfg['images']:
        name = item['name']
        if name in names:
            raise ValueError(f'duplicate image name: {name}')
        names.add(name)
        if item['strategy'] == 'build':
            context = project_path(item['context'])
            recipe = context / 'Containerfile'
            if not recipe.is_file():
                raise ValueError(f'{name}: missing Containerfile')
            from_lines = [line.strip() for line in recipe.read_text().splitlines()
                          if line.strip().upper().startswith('FROM ')]
            if from_lines != ['FROM ${BASE_IMAGE}']:
                raise ValueError(f'{name}: Containerfile must use only the locked BASE_IMAGE')
        if 'assessment' in item:
            project_path(item['assessment'])
        for key in ('artifact', 'composer'):
            if key in item:
                url = urlsplit(item[key]['url'])
                if url.username or url.password or url.query or url.fragment:
                    raise ValueError('download URLs must not contain credentials, signed queries or fragments')
    for item in cfg['images']:
        if item['test'] in ('wordpress', 'phpmyadmin'):
            database = next((i for i in cfg['images'] if i['name'] == item.get('test_database')), None)
            if database is None or database['test'] not in ('mysql', 'mariadb'):
                raise ValueError('web tests require a MySQL/MariaDB manifest fixture')
        elif 'test_database' in item:
            raise ValueError('only web images may have a test database')
    return cfg


def source_ref(item):
    return item['source']['reference'].rsplit(':', 1)[0] + '@' + item['source']['digest']


def source_details(reference):
    raw = run('skopeo', 'inspect', '--raw', 'docker://' + reference, capture=True, binary=True)
    manifest = json.loads(raw)
    if 'manifests' in manifest:
        if '@' in reference:
            raise ValueError('locked digest must identify a single platform manifest, not an index')
        matches = [m for m in manifest['manifests'] if
                   m.get('platform', {}).get('os') == 'linux' and
                   m.get('platform', {}).get('architecture') == 'amd64' and
                   not m.get('platform', {}).get('variant')]
        if len(matches) != 1:
            raise ValueError('source must have exactly one linux/amd64 manifest')
        repository = reference.split('@', 1)[0].rsplit(':', 1)[0]
        return source_details(repository + '@' + matches[0]['digest'])
    digest = sha(raw)
    if '@' in reference and reference.rsplit('@', 1)[1] != digest:
        raise ValueError('source manifest digest mismatch')
    config = json.loads(run('skopeo', 'inspect', '--config', 'docker://' + reference, capture=True))
    if (config.get('os'), config.get('architecture')) != ('linux', 'amd64'):
        raise ValueError('only a linux/amd64 source is supported')
    return {'digest': digest, 'config_digest': manifest['config']['digest'],
            'platform': 'linux/amd64', 'user': config.get('config', {}).get('User', '')}


def fingerprint(item):
    inputs = {'manifest': item, 'files': []}
    if item['strategy'] == 'build':
        context = project_path(item['context'])
        for path in sorted(context.rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc' or path.name == '.env':
                continue
            if ROOT not in path.resolve().parents:
                raise ValueError('build context symlink escapes repository')
            inputs['files'].append({'path': str(path.relative_to(context)), 'sha256': sha(path.read_bytes())})
    if 'test_database' in item:
        database = next(i for i in load_manifest()['images'] if i['name'] == item['test_database'])
        inputs['test_database'] = fingerprint(database)
    return sha(json.dumps(inputs, sort_keys=True).encode())


def image_id(image):
    value = run('podman', 'image', 'inspect', '--format', '{{.Id}}', image, capture=True).strip()
    return value if value.startswith('sha256:') else 'sha256:' + value


def checked_image(image):
    data = json.loads(run('podman', 'image', 'inspect', image, capture=True))[0]
    if (data['Os'], data['Architecture']) != ('linux', 'amd64'):
        raise ValueError('local image must be linux/amd64')
    return image_id(image)


def test_image(item, image):
    args = []
    if item['test'] in ('wordpress', 'phpmyadmin'):
        database = next(i for i in load_manifest()['images'] if i['name'] == item['test_database'])
        if database['test'] not in ('mysql', 'mariadb'):
            raise ValueError('web fixture must be MySQL or MariaDB')
        database_image = checked_image(f"localhost/kurs/{database['name']}:test")
        require_build(database, database_image)
        args = ['--database-image', database_image]
    run(sys.executable, 'scripts/smoke.py', '--image', image, '--type', item['test'],
        '--port', str(item.get('port', 8080)), '--path', item.get('path', '/'), *args)


def import_source(item):
    """Local import for assessment/mirroring. Never writes to any registry."""
    details = source_details(source_ref(item))
    local = f"localhost/kurs/{item['name']}:test"
    with tempfile.TemporaryDirectory(prefix='kurs-mirror-') as directory:
        archive = Path(directory) / 'source.tar'
        source = 'docker://' + source_ref(item)
        try:
            run('podman', 'image', 'exists', details['config_digest'])
        except subprocess.CalledProcessError as exc:
            if exc.returncode != 1:
                raise
        else:
            # A matching immutable config ID includes the rootfs diff IDs. Reuse
            # exact cached source content while still verifying its registry lock.
            cached = Path(directory) / 'cached.tar'
            run('podman', 'save', '--format', 'docker-archive', '--output', cached, details['config_digest'])
            source = 'docker-archive:' + str(cached)
        run('skopeo', 'copy', '--override-os', 'linux', '--override-arch', 'amd64',
            source, f'docker-archive:{archive}:{local}')
        run('podman', 'load', '--input', archive)
    image = checked_image(local)
    if image != details['config_digest']:
        raise ValueError('mirroring changed the source image configuration')
    if details['user'].split(':')[0] in ('', '0', 'root'):
        raise ValueError('mirror source must default to non-root')
    return image


def assess(item):
    if 'assessment' not in item:
        raise ValueError('assessment output path is required')
    image = import_source(item)
    test_image(item, image)
    report = {'name': item['name'], 'source': source_ref(item), 'digest': item['source']['digest'],
              'image_id': image, 'platform': item['platform'], 'status': 'pass',
              'uids': [1001230000, 1002340000], 'gid': 0, 'capabilities': [],
              'no_new_privileges': True, 'tested_at': now()}
    write_json(project_path(item['assessment']), report)


def require_assessment(item):
    report = json.loads(project_path(item['assessment']).read_text())
    expected = {'name': item['name'], 'source': source_ref(item), 'digest': item['source']['digest'],
                'platform': item['platform'], 'status': 'pass', 'uids': [1001230000, 1002340000],
                'gid': 0, 'capabilities': [], 'no_new_privileges': True}
    if any(report.get(key) != value for key, value in expected.items()):
        raise ValueError(f"{item['name']}: missing or stale mirror compatibility assessment")


def build(item):
    if 'test_database' in item:
        database = next(i for i in load_manifest()['images'] if i['name'] == item['test_database'])
        try:
            require_build(database, checked_image(f"localhost/kurs/{database['name']}:test"))
        except (OSError, ValueError, subprocess.CalledProcessError):
            build(database)
    local = f"localhost/kurs/{item['name']}:test"
    if item['strategy'] == 'mirror':
        require_assessment(item)
        image = import_source(item)
    else:
        source_details(source_ref(item))
        args = ['--build-arg', 'BASE_IMAGE=' + source_ref(item)]
        if 'composer' in item:
            args += ['--build-arg', 'COMPOSER_URL=' + item['composer']['url'],
                     '--build-arg', 'COMPOSER_SHA256=' + item['composer']['sha256']]
        if 'artifact' in item:
            args += ['--build-arg', 'APP_URL=' + item['artifact']['url'],
                     '--build-arg', 'APP_SHA256=' + item['artifact']['sha256']]
        run('podman', 'build', '--platform=' + item['platform'], '--pull=always', *args,
            '-f', item['context'] + '/Containerfile', '-t', local, item['context'])
        image = checked_image(local)
    write_json(REPORTS / item['name'] / 'build.json',
               {'name': item['name'], 'image_id': image, 'source': source_ref(item),
                'fingerprint': fingerprint(item), 'built_at': now(), 'strategy': item['strategy'],
                'source_metadata': item['source'], 'platform': item['platform'], 'license': item['license'],
                'artifact': item.get('artifact'), 'build_tool': item.get('composer'),
                'source_commit': os.getenv('GITHUB_SHA'), 'ci_run_id': os.getenv('GITHUB_RUN_ID')})


def require_build(item, image):
    report = json.loads((REPORTS / item['name'] / 'build.json').read_text())
    if report['image_id'] != image or report['fingerprint'] != fingerprint(item):
        raise ValueError('image does not match the current source/build record; rebuild it')
    return report


def verify(item, image):
    from security import audit
    folder = REPORTS / item['name']
    folder.mkdir(parents=True, exist_ok=True)
    # Invalidate old green results before any new test, scanner or policy failure.
    record = require_build(item, image)
    record.update(smoke='pending', security='pending', okd='not-verified')
    write_json(folder / 'verification.json', record)
    test_image(item, image)
    record.update(smoke='pass', uids=[1001230000, 1002340000], tested_at=now())
    write_json(folder / 'verification.json', record)
    policy = audit(item, image, folder, run)
    record.update(security=policy['status'], audited_at=now(), policy=policy,
                  reports={p.name: sha(p.read_bytes()) for p in folder.iterdir()
                           if p.name in ('sbom.cdx.json', 'trivy.json', 'policy.json')})
    write_json(folder / 'verification.json', record)
    if policy['status'] != 'pass':
        raise ValueError(f"{item['name']}: CRITICAL vulnerability policy failed; see {folder / 'policy.json'}")
    return record


def publish(cfg, selected, args):
    if os.environ.get('ALLOW_PUBLISH') != 'yes':
        raise ValueError('Publication disabled; explicit ALLOW_PUBLISH=yes required')
    if args.channel == 'stable':
        raise ValueError('Stable publication disabled until registry-enforced tag immutability is configured and verified')
    tested = []
    for item in selected:
        image = checked_image(f"localhost/kurs/{item['name']}:test")
        record = verify(item, image)
        tested.append((item, image, record))
    for item, image, record in tested:
        folder = REPORTS / item['name']
        folder.mkdir(parents=True, exist_ok=True)
        target = f"{cfg['namespace']}/{item['name']}:candidate-{args.run_id}"
        digestfile = folder / 'published-digest.txt'
        digestfile.unlink(missing_ok=True)
        run('podman', 'push', '--digestfile', digestfile, image, 'docker://' + target)
        digest = digestfile.read_text().strip()
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise ValueError('registry push did not return a valid digest')
        manifest = run('skopeo', 'inspect', '--raw', 'docker://' + target.rsplit(':', 1)[0] + '@' + digest,
                       capture=True, binary=True)
        if sha(manifest) != digest or json.loads(manifest)['config']['digest'] != image:
            raise ValueError('published image config differs from tested/scanned image')
        record.update(published={'reference': target, 'digest': digest, 'published_at': now()})
        write_json(folder / 'publication.json', record)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['list', 'validate', 'build', 'test', 'assess', 'verify', 'catalog', 'updates', 'publish'])
    parser.add_argument('--name', default='all')
    parser.add_argument('--channel', choices=['candidate', 'stable'], default='candidate')
    parser.add_argument('--run-id', default=f"{os.getenv('GITHUB_RUN_ID', 'local')}-{os.getenv('GITHUB_RUN_ATTEMPT', '1')}")
    args = parser.parse_args()
    cfg = load_manifest()
    selected = [i for i in cfg['images'] if args.name in ('all', i['name'])]
    if not selected or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', args.run_id):
        parser.error('unknown image or invalid run id')
    if args.action == 'publish':
        if os.environ.get('ALLOW_PUBLISH') != 'yes':
            parser.error('Publication disabled; explicit ALLOW_PUBLISH=yes required')
        if args.channel == 'stable':
            parser.error('Stable publication disabled until registry-enforced tag immutability is configured and verified')
        publish(cfg, selected, args)
    elif args.action == 'catalog':
        from catalog import generate
        generate(cfg, ROOT, REPORTS, fingerprint)
    elif args.action == 'updates':
        updates = []
        for item in selected:
            current = source_details(item['source']['reference'])
            updates.append({'name': item['name'], 'locked': item['source']['digest'],
                            'upstream': current['digest'], 'update_available': current['digest'] != item['source']['digest']})
        write_json(REPORTS / 'upstream-updates.json', {'checked_at': now(), 'updates': updates})
    elif args.action == 'validate':
        print(f"Valid manifest: {len(cfg['images'])} linux/amd64 images")
    else:
        failures = []
        for item in selected:
            local = f"localhost/kurs/{item['name']}:test"
            if args.action == 'list':
                print(f"{item['name']:18} {item['strategy']:8} {source_ref(item)}")
            elif args.action == 'build':
                build(item)
            elif args.action == 'assess':
                assess(item)
            elif args.action == 'test':
                test_image(item, checked_image(local))
            elif args.action == 'verify':
                try:
                    verify(item, checked_image(local))
                except Exception as exc:
                    print(f"FAIL {item['name']}: {exc}", file=sys.stderr, flush=True)
                    failures.append(item['name'])
        if failures:
            raise SystemExit('Verification failed: ' + ', '.join(failures))


if __name__ == '__main__':
    main()
