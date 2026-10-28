#!/usr/bin/env python3
"""Isolated arbitrary-UID smoke tests; not an OKD SCC verification."""
import argparse
import http.cookiejar
from html.parser import HTMLParser
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import uuid


def cmd(*args, capture=False, timeout=30):
    print('+', ' '.join(args), flush=True)
    result = subprocess.run(args, text=True, capture_output=capture, check=True, timeout=timeout)
    return result.stdout.strip() if capture else ''


def interrupted(signum, frame):
    raise KeyboardInterrupt(f'signal {signum}')


MYSQL_ENV = ['-e', 'MYSQL_USER=kurs', '-e', 'MYSQL_PASSWORD=testpass',
             '-e', 'MYSQL_DATABASE=kurs']
DATABASE_FIXTURE = 'localhost/kurs/mariadb:test'
PHP_SQL = ("mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT); "
           "$db=new mysqli(getenv('WORDPRESS_DB_HOST') ?: getenv('PMA_HOST'), "
           "'kurs', 'testpass', 'kurs'); "
           "$db->query('CREATE TEMPORARY TABLE smoke (n int)'); "
           "$db->query('INSERT INTO smoke VALUES (42)'); "
           "echo $db->query('SELECT n FROM smoke')->fetch_row()[0];")


def sql_check(name, kind):
    if kind in ('wordpress', 'phpmyadmin'):
        result = cmd('podman', 'exec', name, 'php', '-r', PHP_SQL, capture=True)
    else:
        client = 'mariadb' if kind == 'mariadb' else 'mysql'
        result = cmd('podman', 'exec', '-e', 'MYSQL_PWD=testpass', name, client,
                     '--protocol=TCP', '-h', '127.0.0.1', '-u', 'kurs', '-D', 'kurs',
                     '-N', '-B', '-e', 'CREATE TEMPORARY TABLE smoke (n int); '
                     'INSERT INTO smoke VALUES (42); SELECT n FROM smoke;', capture=True)
    if result != '42':
        raise RuntimeError(f'unexpected SQL result: {result}')


def check_http(url, kind):
    with urllib.request.urlopen(url, timeout=2) as response:
        body = response.read()
        if response.status != 200 or not body:
            raise RuntimeError('empty or unsuccessful HTTP response')
        markers = {'wordpress': b'weblog_title', 'phpmyadmin': b'pma_username'}
        marker = markers.get(kind)
        if marker and marker not in body:
            raise RuntimeError(f'missing {kind} form')
        if kind == 'http' and url.endswith('/health') and b'"ok"' not in body:
            raise RuntimeError('invalid health response')


class LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}
        self.action = ''
        self.inside = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form' and attrs.get('id') == 'login_form':
            self.inside = True
            self.action = attrs.get('action', '')
        if self.inside and tag == 'input' and attrs.get('name'):
            self.fields[attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.inside = False


def login_phpmyadmin(url, user='kurs', password='testpass'):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with opener.open(url, timeout=5) as response:
        form = LoginForm()
        form.feed(response.read().decode('utf-8'))
    if 'token' not in form.fields or 'pma_username' not in form.fields:
        raise RuntimeError('missing phpMyAdmin login form/token')
    form.fields.update(pma_username=user, pma_password=password, server='1')
    data = urllib.parse.urlencode(form.fields).encode()
    with opener.open(urllib.parse.urljoin(url, form.action), data=data, timeout=10) as response:
        body = urllib.parse.unquote(response.read().decode('utf-8'))
        if response.status != 200 or 'db=kurs' not in body or 'route=/logout' not in body:
            raise RuntimeError('phpMyAdmin login did not expose the kurs database and logout link')


def cleanup(args):
    # A failed cleanup must not prevent attempts to remove the other resources.
    try:
        result = subprocess.run(args, check=False, timeout=30,
                                stdout=None if args[1] == 'logs' else subprocess.DEVNULL)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f'Cleanup failed: {exc}', flush=True)
        return False


def user_namespace(uid, rootless=True):
    if not rootless:
        return ['--userns=host']
    # Map the caller to the high container UID and GID 0; map image system users
    # to subordinate IDs. Avoid keep-id's gid=0 mapping bug on older Podman/crun.
    return ['--uidmap=0:1:65536', f'--uidmap={uid}:0:1', '--gidmap=0:0:65536']


def test_one(a, uid):
    name = 'kurs-smoke-' + uuid.uuid4().hex
    db_name, network = name + '-db', name + '-net'
    web = a.type in ('wordpress', 'phpmyadmin')
    database_image = getattr(a, 'database_image', DATABASE_FIXTURE)
    mapping = user_namespace(uid, getattr(a, 'rootless', True))
    common = ['--init', '--name', name, '--platform=linux/amd64', '--pull=never',
              *mapping, '--passwd=false',
              '--user', f'{uid}:0', '--cap-drop=ALL',
              '--security-opt=no-new-privileges']
    try:
        if a.type == 'tools':
            cmd('podman', 'run', *common, a.image, 'sh', '-ec',
                'test "$(id -u)" -ne 0; curl --version; dig -v; jq --version; ip -Version; '
                'for tool in bash ping tracepath ncat ps; do command -v "$tool"; done')
        else:
            extra = []
            if a.type == 'postgres':
                extra = ['-e', 'POSTGRESQL_USER=kurs', '-e', 'POSTGRESQL_PASSWORD=testpass',
                         '-e', 'POSTGRESQL_DATABASE=kurs']
            elif a.type in ('mysql', 'mariadb'):
                extra = MYSQL_ENV
            elif web:
                cmd('podman', 'network', 'create', network)
                cmd('podman', 'run', '-d', '--init', '--name', db_name, '--network', network,
                    '--network-alias', 'database', '--platform=linux/amd64', '--pull=never',
                    *mapping, '--passwd=false', '--user', f'{uid}:0',
                    '--cap-drop=ALL', '--security-opt=no-new-privileges', *MYSQL_ENV,
                    database_image)
                extra = ['--network', network]
                if a.type == 'wordpress':
                    extra += ['-e', 'WORDPRESS_DB_HOST=database', '-e', 'WORDPRESS_DB_NAME=kurs',
                              '-e', 'WORDPRESS_DB_USER=kurs', '-e', 'WORDPRESS_DB_PASSWORD=testpass']
                else:
                    extra += ['-e', 'PMA_HOST=database']
            port = {'postgres': '5432', 'mysql': '3306', 'mariadb': '3306'}.get(a.type, a.port)
            command = ['python3', '-m', 'http.server', str(port), '--bind', '0.0.0.0'] if a.type == 'python' else []
            cmd('podman', 'run', '-d', *common, *extra, '-p', f'127.0.0.1::{port}', a.image, *command)
            host_port = cmd('podman', 'port', name, f'{port}/tcp', capture=True).rsplit(':', 1)[-1]
            deadline = time.monotonic() + 120
            while True:
                # An exited process cannot become ready; do not retry it for two minutes.
                for service in ([name, db_name] if web else [name]):
                    if cmd('podman', 'inspect', '--format', '{{.State.Running}}', service, capture=True) != 'true':
                        raise RuntimeError(f'container exited: {service}')
                try:
                    if a.type == 'postgres':
                        result = cmd('podman', 'exec', '-e', 'PGPASSWORD=testpass', name, 'psql',
                                     '-h', '127.0.0.1', '-U', 'kurs', '-d', 'kurs', '-v', 'ON_ERROR_STOP=1',
                                     '-Atc', 'CREATE TEMP TABLE smoke (n int); INSERT INTO smoke VALUES (42); SELECT n FROM smoke;', capture=True)
                        if result.splitlines()[-1:] != ['42']:
                            raise RuntimeError(f'unexpected SQL result: {result}')
                    elif a.type in ('mysql', 'mariadb') or web:
                        sql_check(name, a.type)
                    if a.type not in ('postgres', 'mysql', 'mariadb'):
                        url = f'http://127.0.0.1:{host_port}{a.path}'
                        check_http(url, a.type)
                        if a.type == 'phpmyadmin':
                            login_phpmyadmin(url)
                    actual_uid = cmd('podman', 'exec', name, 'id', '-u', capture=True)
                    if actual_uid != uid:
                        raise RuntimeError(f'unexpected UID: {actual_uid}')
                    break
                except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f'{a.image}: {a.type} failed under UID {uid}') from exc
                    time.sleep(1)
        print(f'PASS {a.image}: {a.type}, uid={uid}')
    except BaseException:
        cleanup(['podman', 'logs', name])
        if web:
            cleanup(['podman', 'logs', db_name])
        raise
    finally:
        cleaned = [cleanup(['podman', 'rm', '-f', '--volumes', '--time=0', name])]
        if web:
            cleaned.append(cleanup(['podman', 'rm', '-f', '--volumes', '--time=0', db_name]))
            cleaned.append(cleanup(['podman', 'network', 'rm', network]))
        if not all(cleaned) and sys.exc_info()[0] is None:
            raise RuntimeError('test resource cleanup failed')


def prepare_database(image=DATABASE_FIXTURE):
    # The manifest build resolves and builds this dependency before web tests.
    cmd('podman', 'image', 'exists', image)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--image', required=True)
    p.add_argument('--database-image', default=DATABASE_FIXTURE)
    p.add_argument('--type', choices=['http', 'postgres', 'python', 'tools', 'mysql', 'mariadb', 'wordpress', 'phpmyadmin'], required=True)
    p.add_argument('--port', default='8080')
    p.add_argument('--path', default='/')
    a = p.parse_args()
    signal.signal(signal.SIGTERM, interrupted)
    rootless = cmd('podman', 'info', '--format', '{{.Host.Security.Rootless}}', capture=True)
    if rootless not in ('true', 'false'):
        raise RuntimeError(f'Unexpected Podman rootless status: {rootless}')
    a.rootless = rootless == 'true'
    if a.type in ('wordpress', 'phpmyadmin'):
        # Require the local manifest dependency before creating resources.
        prepare_database(a.database_image)
    for uid in ('1001230000', '1002340000'):
        test_one(a, uid)


if __name__ == '__main__':
    main()
