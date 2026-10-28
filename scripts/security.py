"""Fail-closed Trivy policy and SBOM generation for an exact OCI archive."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]


def exceptions(path, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    cfg = yaml.safe_load(path.read_text())
    if not isinstance(cfg, dict) or set(cfg) != {'exceptions'} or not isinstance(cfg['exceptions'], list):
        raise ValueError('exceptions file must contain an exceptions list')
    result, keys = [], set()
    for entry in cfg['exceptions']:
        required = {'image', 'cve', 'package', 'reason', 'owner', 'tracking', 'expires'}
        if not isinstance(entry, dict) or set(entry) != required:
            raise ValueError('exception must identify image, CVE, package, reason, owner, tracking and expiry')
        if any(not isinstance(entry[k], str) or not entry[k].strip() for k in required - {'expires'}):
            raise ValueError('exception values must be nonempty strings')
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', entry['image']) or not re.fullmatch(r'CVE-\d{4}-\d{4,}', entry['cve']):
            raise ValueError('exceptions must be scoped to one image and CVE')
        if '*' in entry['package'] or len(entry['reason']) < 10 or not entry['tracking'].startswith('https://'):
            raise ValueError('exception needs a specific package, reason and HTTPS tracking URL')
        expiry = dt.date.fromisoformat(str(entry['expires']))
        if not today <= expiry <= today + dt.timedelta(days=90):
            raise ValueError('exception expired or exceeds 90 days')
        key = (entry['image'], entry['cve'], entry['package'])
        if key in keys:
            raise ValueError('duplicate CVE exception')
        keys.add(key)
        result.append({**entry, 'expires': expiry.isoformat()})
    return result


def evaluate(report, name, allowed, image):
    if (report.get('SchemaVersion') != 2 or report.get('ArtifactType') != 'container_image' or
            report.get('Metadata', {}).get('ImageID') != image):
        raise ValueError('Trivy report is malformed or refers to a different image')
    if not isinstance(report.get('Results'), list) or not any(t.get('Class') == 'os-pkgs' for t in report['Results']):
        return {'status': 'fail', 'blocked': [{'reason': 'OS vulnerability coverage missing',
                 'os': report.get('Metadata', {}).get('OS')}], 'waived': [],
                'rule': 'Unsupported or unscanned OS cannot pass the vulnerability gate'}
    blocked, waived = [], []
    counts = {level: 0 for level in ('UNKNOWN', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')}
    for target in report['Results']:
        vulnerabilities = target.get('Vulnerabilities') or []
        if not isinstance(vulnerabilities, list):
            raise ValueError('malformed vulnerability list')
        for vulnerability in vulnerabilities:
            if vulnerability.get('Severity') not in {'UNKNOWN', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}:
                raise ValueError('vulnerability without a recognized severity')
            counts[vulnerability['Severity']] += 1
            if vulnerability.get('Severity') != 'CRITICAL':
                continue
            finding = {'target': target['Target'], 'cve': vulnerability['VulnerabilityID'],
                       'package': vulnerability['PkgName'], 'installed': vulnerability['InstalledVersion'],
                       'fixed': vulnerability.get('FixedVersion', '')}
            exception = next((e for e in allowed if (e['image'], e['cve'], e['package']) ==
                              (name, finding['cve'], finding['package'])), None)
            if exception:
                waived.append({**finding, 'exception': exception})
            else:
                blocked.append(finding)
    return {'status': 'fail' if blocked else 'pass', 'blocked': blocked, 'waived': waived,
            'severity_counts': counts,
            'rule': 'All CRITICAL findings, including unfixed; exact scoped exceptions expire within 90 days'}


def audit(item, image, folder, run):
    lock = json.loads((ROOT / 'tools.lock.json').read_text())
    versions = {name: run(name, '--version', capture=True).strip() for name in ('trivy', 'syft')}
    for name, version in versions.items():
        expected = re.escape(lock[name]['version'].removeprefix('v'))
        if not re.search(r'(?:^|\s)v?' + expected + r'(?:\s|$)', version.splitlines()[0]):
            raise ValueError(f'{name}: install the version pinned in tools.lock.json')
    allowed = exceptions(ROOT / 'security/exceptions.yaml')
    with tempfile.TemporaryDirectory(prefix='kurs-audit-') as directory:
        archive = Path(directory) / 'image.tar'
        docker_config = Path(directory) / 'docker-config'
        docker_config.mkdir()
        (docker_config / 'config.json').write_text('{"auths": {}}')
        scanner_env = {**{k: v for k, v in os.environ.items() if not k.startswith('TRIVY_')},
                       'DOCKER_CONFIG': str(docker_config),
                       'TRIVY_CACHE_DIR': os.getenv('TRIVY_CACHE_DIR', str(ROOT / '.cache/trivy'))}
        run('podman', 'save', '--format', 'docker-archive', '--output', archive, image)
        manifest = json.loads(run('skopeo', 'inspect', '--raw', 'docker-archive:' + str(archive), capture=True))
        if manifest['config']['digest'] != image:
            raise ValueError('exported archive does not match tested image')
        run('syft', 'scan', 'docker-archive:' + str(archive), '-o', 'cyclonedx-json=' + str(folder / 'sbom.cdx.json'))
        sbom = json.loads((folder / 'sbom.cdx.json').read_text())
        if sbom.get('bomFormat') != 'CycloneDX' or not sbom.get('components'):
            raise ValueError('Syft produced an empty or invalid SBOM')
        run('trivy', 'image', '--input', archive, '--scanners', 'vuln', '--format', 'json',
            '--output', folder / 'trivy.json', '--exit-code', '0', '--ignore-unfixed=false',
            '--severity', 'UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL', '--config', ROOT / 'security/trivy.yaml', '--ignorefile', ROOT / 'security/empty.trivyignore', env=scanner_env)
    report = json.loads((folder / 'trivy.json').read_text())
    policy = evaluate(report, item['name'], allowed, image)
    metadata = Path(scanner_env['TRIVY_CACHE_DIR']) / 'db/metadata.json'
    policy.update(tool_versions=versions, vulnerability_database=json.loads(metadata.read_text()),
                  tools_lock_sha256=hashlib.sha256((ROOT / 'tools.lock.json').read_bytes()).hexdigest(),
                  exception_policy_sha256=hashlib.sha256((ROOT / 'security/exceptions.yaml').read_bytes()).hexdigest())
    (folder / 'policy.json').write_text(json.dumps(policy, indent=2) + '\n')
    return policy
