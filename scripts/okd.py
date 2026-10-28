#!/usr/bin/env python3
"""Optional, digest-specific OKD verification. Never builds or publishes images.

Reports deliberately contain no raw oc errors, Pod specs, logs or credentials.
Controllers create Pods so admission evaluates the test service account's SCCs.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import tempfile
import time
import uuid

import library
import smoke

DIGEST = r'sha256:[0-9a-f]{64}'
DATABASES = ('postgres', 'mysql', 'mariadb')
WEB = ('wordpress', 'phpmyadmin')
WRITE_PATHS = {
    'nginx': '/var/lib/nginx', 'postgresql': '/var/lib/postgresql/data',
    'mysql': '/var/lib/mysql', 'mariadb': '/var/lib/kurs-mariadb',
    'wordpress': '/opt/app-root/src', 'phpmyadmin': '/opt/app-root/src/tmp',
    'flask-lab': '/opt/app', 'python': '/tmp', 'network-tools': '/tmp',
}
TOOLS = ('test "$(id -u)" -ne 0; curl --version; dig -v; jq --version; ip -Version; '
         'for tool in bash ping tracepath ncat ps; do command -v "$tool"; done')


class CheckError(ValueError):
    """A safe, locally defined validation message; never third-party output."""


class OcError(RuntimeError):
    pass


def oc(*args, data=None, timeout=45):
    # Capture stderr even on success: neither credentials nor admission diagnostics
    # from third-party policies should enter artifacts or CI output.
    try:
        result = subprocess.run(['oc', '--request-timeout=20s', *map(str, args)],
                                input=json.dumps(data) if data is not None else None,
                                text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OcError('oc unavailable or request timed out') from exc
    if result.returncode:
        raise OcError('oc request failed (details suppressed; inspect cluster locally)')
    return result.stdout.strip()


def get(*args):
    return json.loads(oc('get', *args, '-o', 'json'))


def candidates(data, cfg):
    if not isinstance(data, dict):
        raise CheckError('candidates must be a JSON object: image name -> repository@sha256:digest')
    items = {i['name']: i for i in cfg['images']}
    for name, ref in data.items():
        if name not in items or not isinstance(ref, str) or not re.fullmatch(
                re.escape(cfg['namespace'] + '/' + name) + '@' + DIGEST, ref):
            raise CheckError('candidate must name a manifest image and its exact registry digest; tags are forbidden')
        dependency = items[name].get('test_database')
        if dependency and dependency not in data:
            raise CheckError(f'{name} requires the published {dependency} candidate digest too')
    return [i for i in cfg['images'] if i['name'] in data]


def secret_env(name):
    return {'name': name, 'valueFrom': {'secretKeyRef': {'name': 'test-db', 'key': 'password'}}}


def workload(item, ref, namespace):
    name, kind = item['name'], item['test']
    port = {'postgres': 5432, 'mysql': 3306, 'mariadb': 3306}.get(kind, item.get('port', 8080))
    container = {'name': 'test', 'image': ref, 'imagePullPolicy': 'Always',
                 'resources': {'requests': {'cpu': '100m', 'memory': '128Mi'},
                               'limits': {'cpu': '2', 'memory': '1Gi'}},
                 'securityContext': {'allowPrivilegeEscalation': False, 'privileged': False,
                                     'capabilities': {'drop': ['ALL']}, 'runAsNonRoot': True,
                                     'seccompProfile': {'type': 'RuntimeDefault'}},
                 'ports': [{'containerPort': port}], 'env': []}
    env = container['env']
    if kind in DATABASES or kind in WEB:
        env.append(secret_env('KURS_DB_PASSWORD'))
    if kind == 'postgres':
        env += [{'name': 'POSTGRESQL_USER', 'value': 'kurs'},
                {'name': 'POSTGRESQL_DATABASE', 'value': 'kurs'}, secret_env('POSTGRESQL_PASSWORD')]
    elif kind in ('mysql', 'mariadb'):
        env += [{'name': 'MYSQL_USER', 'value': 'kurs'}, {'name': 'MYSQL_DATABASE', 'value': 'kurs'},
                secret_env('MYSQL_PASSWORD')]
    elif kind in WEB:
        if kind == 'wordpress':
            env += [{'name': 'WORDPRESS_DB_HOST', 'value': item['test_database']},
                    {'name': 'WORDPRESS_DB_NAME', 'value': 'kurs'},
                    {'name': 'WORDPRESS_DB_USER', 'value': 'kurs'}, secret_env('WORDPRESS_DB_PASSWORD')]
        else:
            env.append({'name': 'PMA_HOST', 'value': item['test_database']})
    if kind == 'tools':
        container['command'] = ['sh', '-ec', TOOLS + '; exec sleep 3600']
        probe = {'exec': {'command': ['sh', '-ec', 'test -r /proc/1/status']}}
    elif kind in DATABASES:
        probe = {'tcpSocket': {'port': port}}
    else:
        if kind == 'python':
            container['command'] = ['python3', '-m', 'http.server', str(port), '--bind', '0.0.0.0']
        probe = {'httpGet': {'path': item.get('path', '/'), 'port': port}}
    container['readinessProbe'] = {**probe, 'periodSeconds': 3, 'timeoutSeconds': 2, 'failureThreshold': 5}
    container['startupProbe'] = {**probe, 'periodSeconds': 3, 'timeoutSeconds': 2, 'failureThreshold': 100}
    labels = {'app': name, 'app.kubernetes.io/part-of': 'kurs-okd-smoke'}
    return {'apiVersion': 'apps/v1', 'kind': 'Deployment',
            'metadata': {'name': name, 'namespace': namespace},
            'spec': {'replicas': 1, 'selector': {'matchLabels': labels},
                     'template': {'metadata': {'labels': labels}, 'spec': {
                         'serviceAccountName': 'kurs-smoke', 'automountServiceAccountToken': False,
                         'nodeSelector': {'kubernetes.io/os': 'linux', 'kubernetes.io/arch': 'amd64'},
                         'terminationGracePeriodSeconds': 10,
                         'securityContext': {'runAsNonRoot': True, 'seccompProfile': {'type': 'RuntimeDefault'}},
                         'containers': [container]}}}}


def admitted(pod, ref, source, uid_range):
    """Validate actual admission, runtime identity and readiness; never trust labels alone."""
    spec = pod['spec']
    if pod['metadata'].get('annotations', {}).get('openshift.io/scc') != 'restricted-v2':
        raise CheckError('Pod was not admitted with restricted-v2')
    if spec.get('nodeSelector') != {'kubernetes.io/os': 'linux', 'kubernetes.io/arch': 'amd64'}:
        raise CheckError('unexpected scheduling platform')
    if spec.get('serviceAccountName') != 'kurs-smoke' or spec.get('automountServiceAccountToken') is not False:
        raise CheckError('unexpected service account/token mount')
    if any(spec.get(k, False) for k in ('hostNetwork', 'hostPID', 'hostIPC')):
        raise CheckError('host access is forbidden')
    if any('hostPath' in v for v in spec.get('volumes', [])) or spec.get('initContainers') or spec.get('ephemeralContainers'):
        raise CheckError('unexpected volumes or sidecars')
    if len(spec['containers']) != 1 or spec['containers'][0]['image'] != ref:
        raise CheckError('unexpected container/image')
    container = spec['containers'][0]
    pod_security = spec.get('securityContext', {})
    security = {**pod_security, **container.get('securityContext', {})}
    start, length = map(int, uid_range.split('/'))
    uid = security.get('runAsUser', -1)
    if not start <= uid < start + length or uid <= 0:
        raise CheckError('UID was not allocated by the namespace')
    if (security.get('runAsNonRoot') is not True or security.get('allowPrivilegeEscalation') is not False
            or security.get('privileged', False) or security.get('capabilities') != {'drop': ['ALL']}
            or security.get('seccompProfile') != {'type': 'RuntimeDefault'}
            or not security.get('seLinuxOptions', {}).get('level')):
        raise CheckError('admitted security context does not satisfy restricted test policy')
    statuses = pod['status'].get('containerStatuses', [])
    if len(statuses) != 1 or not statuses[0].get('ready') or statuses[0].get('restartCount', 0) != 0:
        raise CheckError('container is not ready or restarted')
    image_id = statuses[0].get('imageID', '')
    match = re.search(DIGEST + '$', image_id)
    # CRI-O can report either the pulled manifest digest or the image config ID.
    if not match or match[0] not in (source['digest'], source['config_digest']):
        raise CheckError('runtime imageID does not match the locked manifest/config')
    return {'scc': 'restricted-v2', 'uid': uid, 'security_context': security,
            'runtime_image_id': image_id, 'pod_uid': pod['metadata']['uid'],
            'ready': True, 'restarts': 0}


def wait_ready(namespace, name, timeout):
    deadline = time.monotonic() + timeout
    while True:
        pods = get('pods', '-n', namespace, '-l', 'app=' + name)['items']
        if len(pods) == 1:
            pod = pods[0]
            statuses = pod.get('status', {}).get('containerStatuses', [])
            for status in statuses:
                if status.get('restartCount', 0) or 'terminated' in status.get('state', {}):
                    raise CheckError('container exited or restarted during startup')
                if status.get('state', {}).get('waiting', {}).get('reason') in ('ErrImagePull', 'ImagePullBackOff', 'InvalidImageName'):
                    raise CheckError('candidate could not be pulled')
            if statuses and all(s.get('ready') for s in statuses):
                return pod
        if time.monotonic() >= deadline:
            raise CheckError('Pod readiness timeout (including scheduling/admission)')
        time.sleep(2)


def execute(namespace, pod, *args):
    return oc('exec', '-n', namespace, pod, '-c', 'test', '--', *args)


def runtime_checks(item, namespace, pod, uid):
    name, kind = item['name'], item['test']
    pod_name = pod['metadata']['name']
    if execute(namespace, pod_name, 'id', '-u') != str(uid):
        raise CheckError('runtime UID differs from admission')
    # Check kernel enforcement, not just the Pod's declared securityContext.
    status = execute(namespace, pod_name, 'cat', '/proc/1/status')
    fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
    if fields.get('NoNewPrivs', '').strip() != '1' or int(fields.get('CapEff', '1').strip(), 16) != 0:
        raise CheckError('runtime privileges exceed policy')
    path = WRITE_PATHS[name]
    execute(namespace, pod_name, 'sh', '-ec',
            'test "$(id -u)" -ne 0; f=$(mktemp "$1/.kurs-write-XXXXXX"); '
            'printf verified > "$f"; test "$(cat "$f")" = verified; rm "$f"', 'check', path)
    if kind == 'tools':
        execute(namespace, pod_name, 'sh', '-ec', TOOLS)
    elif kind == 'postgres':
        result = execute(namespace, pod_name, 'sh', '-ec',
                         'export PGPASSWORD="$KURS_DB_PASSWORD"; exec psql -h 127.0.0.1 -U kurs -d kurs '
                         '-v ON_ERROR_STOP=1 -Atc "CREATE TEMP TABLE smoke (n int); '
                         'INSERT INTO smoke VALUES (42); SELECT n FROM smoke;"')
        if result.splitlines()[-1:] != ['42']:
            raise CheckError('unexpected PostgreSQL write/read result')
    elif kind in ('mysql', 'mariadb'):
        client = 'mariadb' if kind == 'mariadb' else 'mysql'
        result = execute(namespace, pod_name, 'sh', '-ec',
                         'export MYSQL_PWD="$KURS_DB_PASSWORD"; exec ' + client +
                         ' --protocol=TCP -h 127.0.0.1 -u kurs -D kurs -N -B '
                         '-e "CREATE TEMPORARY TABLE smoke (n int); INSERT INTO smoke VALUES (42); SELECT n FROM smoke;"')
        if result != '42':
            raise CheckError('unexpected SQL write/read result')
    elif kind in WEB:
        sql = ("mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT); "
               "$db=new mysqli(getenv('WORDPRESS_DB_HOST') ?: getenv('PMA_HOST'), "
               "'kurs', getenv('KURS_DB_PASSWORD'), 'kurs'); "
               "$db->query('CREATE TEMPORARY TABLE smoke (n int)'); "
               "$db->query('INSERT INTO smoke VALUES (42)'); "
               "echo $db->query('SELECT n FROM smoke')->fetch_row()[0];")
        if execute(namespace, pod_name, 'php', '-r', sql) != '42':
            raise CheckError('unexpected application SQL write/read result')
    return ['runtime-uid', 'no-new-privileges', 'zero-capabilities', 'file-write-read-delete',
            'sql-write-read' if kind in (*DATABASES, *WEB) else 'tools' if kind == 'tools' else 'runtime']


@contextmanager
def forward(namespace, pod, port):
    # Let oc allocate the local port, and keep its diagnostics out of reports.
    with tempfile.TemporaryFile(mode='w+') as output:
        process = subprocess.Popen(['oc', '-n', namespace, 'port-forward', '--address=127.0.0.1',
                                    'pod/' + pod, ':' + str(port)], stdout=output, stderr=output, text=True)
        try:
            deadline = time.monotonic() + 30
            while True:
                output.seek(0)
                match = re.search(r'Forwarding from 127\.0\.0\.1:(\d+) ->', output.read())
                if match:
                    yield 'http://127.0.0.1:' + match[1]
                    return
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise CheckError('port-forward did not become ready')
                time.sleep(.2)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def verify_one(item, ref, source, namespace, uid_range, timeout, password):
    pod = wait_ready(namespace, item['name'], timeout)
    evidence = admitted(pod, ref, source, uid_range)
    checks = runtime_checks(item, namespace, pod, evidence['uid'])
    if item['test'] not in (*DATABASES, 'tools'):
        with forward(namespace, pod['metadata']['name'], item.get('port', 8080)) as base:
            url = base + item.get('path', '/')
            smoke.check_http(url, item['test'])
            checks.append('http-content')
            if item['test'] == 'phpmyadmin':
                smoke.login_phpmyadmin(url, password=password)
                checks.append('web-login')
    # Recheck readiness/restarts/identity after functional tests.
    final = get('pod', pod['metadata']['name'], '-n', namespace)
    if admitted(final, ref, source, uid_range) != evidence:
        raise CheckError('Pod identity/security changed during verification')
    return {**evidence, 'registry_manifest_digest': source['digest'],
            'registry_config_digest': source['config_digest'], 'checks': checks, 'tested_at': library.now()}


def safe_reason(exc):
    # Unexpected exception strings may embed input, SQL output, URLs or credentials.
    if isinstance(exc, CheckError):
        return str(exc)
    if isinstance(exc, OcError):
        return 'cluster-request-failed'
    if isinstance(exc, KeyboardInterrupt):
        return 'interrupted'
    return 'verification-failed'


def cleanup_namespace(namespace):
    raw = oc('get', 'namespace', namespace, '--ignore-not-found=true', '-o', 'json')
    if not raw:
        return
    ns = json.loads(raw)
    if ns['metadata'].get('labels', {}).get('kurs-library-run') != namespace:
        raise OcError('namespace ownership does not match this run')
    oc('delete', 'namespace', namespace, '--ignore-not-found=true', '--wait=true',
       '--timeout=120s', timeout=130)


def verify(cfg, refs, output, timeout=300):
    items = candidates(refs, cfg)
    namespace = 'kurs-okd-' + uuid.uuid4().hex[:16]
    report = {'schema_version': 1, 'status': 'pending', 'started_at': library.now(),
              'source_commit': os.getenv('GITHUB_SHA'), 'ci_run_id': os.getenv('GITHUB_RUN_ID'),
              'namespace': namespace, 'cluster_version': None, 'cleanup': 'not-needed',
              'test_definition_sha256': library.sha(Path(__file__).read_bytes() + Path(smoke.__file__).read_bytes()),
              'images': [{'name': i['name'], 'reference': refs[i['name']], 'platform': i['platform'],
                          'status': 'pending', 'okd_status': 'not-verified'} for i in items]}
    save = lambda: library.write_json(output, report)
    save()  # Overwrite a previous green result before touching any cluster.
    if not items:
        report.update(reason='no-published-candidates', finished_at=library.now())
        save()
        return report
    try:
        version = get('clusterversion', 'version')['status']['desired']['version']
        if not isinstance(version, str) or not version:
            raise CheckError('missing cluster version')
        if oc('auth', 'can-i', 'create', 'namespaces') != 'yes':
            raise OcError('namespace permission unavailable')
        report['cluster_version'] = version
    except (OcError, ValueError, KeyError):
        report.update(reason='cluster-unavailable-or-not-authorized', finished_at=library.now())
        save()
        return report
    # Verify registry availability, single-platform manifests and exact content.
    # A registry failure with an available cluster is a failed candidate check.
    attempted_namespace = False
    try:
        sources = {i['name']: library.source_details(refs[i['name']]) for i in items}
        attempted_namespace = True
        report['cleanup'] = 'pending'
        save()
        oc('create', '-f', '-', data={'apiVersion': 'v1', 'kind': 'Namespace',
           'metadata': {'name': namespace, 'labels': {'app.kubernetes.io/part-of': 'kurs-okd-smoke',
                          'kurs-library-run': namespace,
                          'pod-security.kubernetes.io/enforce': 'restricted',
                          'pod-security.kubernetes.io/enforce-version': 'latest'}}})
        # OpenShift assigns UID/MCS ranges asynchronously.
        deadline = time.monotonic() + 30
        while True:
            ns = get('namespace', namespace)
            uid_range = ns['metadata'].get('annotations', {}).get('openshift.io/sa.scc.uid-range', '')
            if re.fullmatch(r'[1-9][0-9]*/[1-9][0-9]*', uid_range):
                break
            if time.monotonic() >= deadline:
                raise CheckError('namespace did not receive a UID allocation')
            time.sleep(1)
        oc('create', '-f', '-', data={'apiVersion': 'v1', 'kind': 'ServiceAccount',
           'metadata': {'name': 'kurs-smoke', 'namespace': namespace}, 'automountServiceAccountToken': False})
        password = secrets.token_urlsafe(32)
        oc('create', '-f', '-', data={'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
           'metadata': {'name': 'test-db', 'namespace': namespace}, 'stringData': {'password': password}})
        # All DBs before web apps, so fixture readiness is established first.
        ordered = sorted(items, key=lambda i: i['test'] in WEB)
        for item in ordered:
            row = next(r for r in report['images'] if r['name'] == item['name'])
            try:
                dependency = item.get('test_database')
                if dependency and next(r for r in report['images'] if r['name'] == dependency)['status'] != 'pass':
                    raise CheckError('database fixture did not pass')
                oc('create', '-f', '-', data=workload(item, refs[item['name']], namespace))
                if item['test'] in ('mysql', 'mariadb'):
                    oc('create', '-f', '-', data={'apiVersion': 'v1', 'kind': 'Service',
                       'metadata': {'name': item['name'], 'namespace': namespace},
                       'spec': {'selector': {'app': item['name']}, 'ports': [{'port': 3306, 'targetPort': 3306}]}})
                row.update(verify_one(item, refs[item['name']], sources[item['name']], namespace,
                                      uid_range, timeout, password), status='pass')
            except Exception as exc:
                row.update(status='fail', reason=safe_reason(exc))
            save()
        report['status'] = 'pass' if all(r['status'] == 'pass' for r in report['images']) else 'fail'
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status='fail', reason=safe_reason(exc))
    finally:
        if attempted_namespace:
            try:
                # Only the generated run namespace is ever deleted. Wait for removal.
                cleanup_namespace(namespace)
                report['cleanup'] = 'pass'
            except (Exception, KeyboardInterrupt):
                report.update(status='fail', cleanup='fail', reason='namespace-cleanup-failed')
        report['finished_at'] = library.now()
        if report['status'] == 'pass' and report['cleanup'] == 'pass':
            for row in report['images']:
                row['okd_status'] = 'okd-verified'
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, required=True, help='JSON object name -> published repository@sha256:digest')
    parser.add_argument('--output', type=Path, default=library.REPORTS / 'okd/result.json')
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    if not 30 <= args.timeout <= 600:
        parser.error('timeout must be between 30 and 600 seconds per image')
    signal.signal(signal.SIGTERM, smoke.interrupted)
    try:
        refs = json.loads(args.candidates.read_text(), object_pairs_hook=unique_json)
        report = verify(library.load_manifest(), refs, args.output, args.timeout)
    except (ValueError, OSError) as exc:
        # Input errors fail even without a cluster, and cannot reuse green evidence.
        library.write_json(args.output, {'schema_version': 1, 'status': 'fail',
                                        'reason': 'invalid-input', 'finished_at': library.now(), 'images': []})
        parser.exit(1, 'Invalid candidate input; see docs/OKD.md\n')
    print(f"OKD {report['status']}; report: {args.output}")
    raise SystemExit(1 if report['status'] == 'fail' else 0)


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CheckError('duplicate JSON key')
        result[key] = value
    return result


if __name__ == '__main__':
    main()
