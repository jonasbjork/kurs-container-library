"""Generate a catalog from the manifest and matching verification records."""
import json
import hashlib
import shlex


def generate(cfg, root, reports, fingerprint):
    rows = []
    for item in cfg['images']:
        path = reports / item['name'] / 'verification.json'
        evidence = json.loads(path.read_text()) if path.is_file() else {}
        if evidence.get('fingerprint') != fingerprint(item):
            evidence = {}
        security_status = evidence.get('security', 'not-scanned')
        if security_status == 'pass':
            policy = evidence.get('policy', {})
            policy_file = root / 'security/exceptions.yaml'
            tools_file = root / 'tools.lock.json'
            if (not policy_file.is_file() or not tools_file.is_file() or
                policy.get('exception_policy_sha256') != hashlib.sha256(policy_file.read_bytes()).hexdigest() or
                policy.get('tools_lock_sha256') != hashlib.sha256(tools_file.read_bytes()).hexdigest()):
                security_status = 'stale'
        row = {**item, 'target': f"{cfg['namespace']}/{item['name']}:{item['version']}",
               'published': None, 'local_image_id': evidence.get('image_id'),
               'podman_status': 'podman-tested' if evidence.get('smoke') == 'pass' else 'not-verified',
               'security_status': security_status, 'okd_status': 'not-verified',
               'tested_at': evidence.get('tested_at'), 'policy': evidence.get('policy'),
               'start_command': shlex.join(['podman', 'run', '--rm', '--platform=linux/amd64',
                   '--cap-drop=ALL', '--security-opt=no-new-privileges',
                   *(['-it'] if item['test'] in ('tools', 'python') else []),
                   *(['-p', f"127.0.0.1:{item.get('port', 8080)}:{item.get('port', 8080)}"] if item['test'] not in ('postgres', 'mysql', 'mariadb', 'tools', 'python') else []),
                   *[arg for env in item['environment'] for arg in ('-e', env)],
                   f"localhost/kurs/{item['name']}:test", *(['python3'] if item['test'] == 'python' else [])])}
        publication = reports / item['name'] / 'publication.json'
        if publication.is_file():
            published = json.loads(publication.read_text())
            if published.get('fingerprint') == fingerprint(item) and published.get('image_id') == evidence.get('image_id'):
                row['published'] = published['published']
        okd_path = reports / 'okd/result.json'
        if okd_path.is_file() and row['published']:
            okd = json.loads(okd_path.read_text())
            exact = f"{cfg['namespace']}/{item['name']}@{row['published']['digest']}"
            matches = [r for r in okd.get('images', []) if r.get('reference') == exact and r.get('name') == item['name']]
            if (okd.get('schema_version') == 1 and okd.get('status') == 'pass'
                    and okd.get('cleanup') == 'pass' and okd.get('cluster_version')
                    and okd.get('test_definition_sha256') and len(matches) == 1
                    and matches[0].get('status') == 'pass' and matches[0].get('okd_status') == 'okd-verified'):
                row['okd_status'] = 'okd-verified'
                row['okd_verification'] = {'reference': exact, 'cluster_version': okd['cluster_version'],
                                           'tested_at': matches[0]['tested_at'],
                                           'test_definition_sha256': okd['test_definition_sha256']}
        rows.append(row)
    output = root / 'catalog'
    output.mkdir(exist_ok=True)
    (output / 'images.json').write_text(json.dumps({'schema_version': 1, 'images': rows}, indent=2, ensure_ascii=False) + '\n')
    lines = ['# Kursimages', '', 'Genererad från images.yaml. Versionsreferenser i Quay är planerade tills publicering anges.',
             'Lokala image-ID:n identifierar testade byggen; de är inte publicerade registry-digests.', '',
             '| Image | Kursversion | Strategi | Upstream-version | Podman | Säkerhet | OKD |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for row in rows:
        lines.append(f"| {row['name']} | {row['version']} | {row['strategy']} | {row.get('artifact', row['source'])['version']} | {row['podman_status']} | {row['security_status']} | {row['okd_status']} |")
    for row in rows:
        lines += ['', f"## {row['name']}", '', row['description'], '',
                  f"- Källa: [{row['source']['reference']}]({row['source']['documentation']})",
                  f"- Låst digest: `{row['source']['digest']}`", f"- Plattform: `{row['platform']}`",
                  f"- Licenser: {row['license']}", f"- Image-standardkommando: `{shlex.join(row['command'])}`",
                  f"- Lokalt startanrop: `{row['start_command']}`",
                  f"- Runtime-variabler (sätt i miljön före start): `{', '.join(row['environment']) or 'inga obligatoriska'}`",
                  '- Databas-/appvariabler, nätverk och volymer: se [README](../README.md).',
                  f"- Testad image: `{row['local_image_id'] or 'inte verifierad för aktuella källor'}`",
                  f"- Publicerad referens: `{json.dumps(row['published']) if row['published'] else 'inte publicerad'}`",
                  f"- OKD-bevis för exakt publicerad digest: `{json.dumps(row.get('okd_verification'), ensure_ascii=False) if row.get('okd_verification') else 'inte verifierad'}`"]
    (output / 'README.md').write_text('\n'.join(lines) + '\n')
