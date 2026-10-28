import argparse
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1] / 'scripts'))
import library
import smoke


class PipelineTests(unittest.TestCase):
    def test_manifest(self):
        self.assertEqual({i['name'] for i in library.load_manifest()['images']},
                         {'nginx', 'postgresql', 'python', 'network-tools', 'flask-lab',
                          'mysql', 'mariadb', 'wordpress', 'phpmyadmin'})

    def test_invalid_manifest(self):
        for change in ({'strategy': 'mirror'}, {'version': 1}, {'context': '../'},
                       {'test': 'unknown'}, {'port': 80}, {'path': 'health'}):
            cfg = library.load_manifest()
            cfg['images'][0].update(change)
            with patch.object(library.yaml, 'safe_load', return_value=cfg):
                with self.assertRaises(ValueError):
                    library.load_manifest()

    def test_duplicate(self):
        cfg = library.load_manifest()
        cfg['images'].append(cfg['images'][0])
        with patch.object(library.yaml, 'safe_load', return_value=cfg):
            with self.assertRaises(ValueError):
                library.load_manifest()

    def invoke(self, args):
        with patch.object(sys, 'argv', ['library.py', *args]):
            library.main()

    def test_publish_disabled(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(library, 'run') as run:
            with self.assertRaises(SystemExit):
                self.invoke(['publish'])
            run.assert_not_called()

    def test_stable_disabled_even_with_opt_in(self):
        with patch.dict('os.environ', {'ALLOW_PUBLISH': 'yes'}), patch.object(library, 'run') as run:
            with self.assertRaises(SystemExit):
                self.invoke(['publish', '--channel', 'stable'])
            run.assert_not_called()

    def test_failure_blocks_all_pushes(self):
        with patch.dict('os.environ', {'ALLOW_PUBLISH': 'yes'}), patch.object(library, 'run', return_value='sha256:123') as run:
            with patch.object(library, 'test_image', side_effect=[None, RuntimeError('failed')]):
                with self.assertRaises(RuntimeError):
                    self.invoke(['publish'])
            self.assertFalse(any('push' in c.args for c in run.call_args_list))

    def test_publish_uses_tested_id(self):
        with patch.dict('os.environ', {'ALLOW_PUBLISH': 'yes'}), patch.object(library, 'run', return_value='sha256:123') as run:
            with patch.object(library, 'test_image') as test:
                self.invoke(['publish', '--name', 'nginx', '--run-id', 'unit'])
            test.assert_called_once_with(library.load_manifest()['images'][0], 'sha256:123')
            self.assertEqual(run.call_args.args, ('podman', 'push', 'sha256:123', 'docker://quay.io/kurs/nginx:candidate-unit'))

    def test_tools_failure_and_interrupt_cleanup(self):
        for error in (subprocess.CalledProcessError(1, 'podman'), KeyboardInterrupt()):
            with patch.object(smoke, 'cmd', side_effect=error), patch.object(smoke.subprocess, 'run') as run:
                with self.assertRaises(type(error)):
                    smoke.test_one(argparse.Namespace(type='tools', image='test'), '1001230000')
                self.assertEqual(run.call_args.args[0][:4], ['podman', 'rm', '-f', '--volumes'])
                self.assertEqual(run.call_args_list[0].args[0][1], 'logs')

    def test_tools_cannot_mask_failure(self):
        with patch.object(smoke, 'cmd') as cmd, patch.object(smoke.subprocess, 'run'):
            smoke.test_one(argparse.Namespace(type='tools', image='test'), '1001230000')
        self.assertNotIn('||', cmd.call_args.args[-1])
        self.assertIn('-ec', cmd.call_args.args)
        self.assertIn('--uidmap=1001230000:0:1', cmd.call_args.args)
        self.assertIn('--gidmap=0:0:65536', cmd.call_args.args)
        self.assertIn('--passwd=false', cmd.call_args.args)
        self.assertIn('--platform=linux/amd64', cmd.call_args.args)

    def test_mysql_and_mariadb_require_sql_result(self):
        for kind in ('mysql', 'mariadb', 'wordpress', 'phpmyadmin'):
            with self.subTest(kind=kind), patch.object(smoke, 'cmd', return_value='0'):
                with self.assertRaises(RuntimeError):
                    smoke.sql_check('test', kind)
            with patch.object(smoke, 'cmd', return_value='42') as cmd:
                smoke.sql_check('test', kind)
                self.assertIn('podman', cmd.call_args.args)

    def test_webapps_reject_error_pages_with_http_200(self):
        for kind, marker in [('wordpress', b'weblog_title'), ('phpmyadmin', b'pma_username')]:
            with patch.object(smoke.urllib.request, 'urlopen') as request:
                response = request.return_value.__enter__.return_value
                response.status = 200
                response.read.return_value = b'database connection error'
                with self.assertRaises(RuntimeError):
                    smoke.check_http('http://localhost/', kind)
                response.read.return_value = marker
                smoke.check_http('http://localhost/', kind)

    def test_webapp_cleanup_on_database_start_failure(self):
        for kind in ('wordpress', 'phpmyadmin'):
            with patch.object(smoke, 'cmd', side_effect=[None, RuntimeError('db failed')]), patch.object(smoke.subprocess, 'run') as run:
                with self.assertRaises(RuntimeError):
                    smoke.test_one(argparse.Namespace(type=kind, image='test'), '1001230000')
                commands = [c.args[0] for c in run.call_args_list]
                self.assertEqual(sum(c[1:4] == ['rm', '-f', '--volumes'] for c in commands), 2)
                self.assertEqual(commands[-1][:3], ['podman', 'network', 'rm'])

    def test_manifest_malformed_structures(self):
        for cfg in (None, [], {}, {'namespace': 'quay.io/kurs', 'images': []},
                    {'namespace': 'quay.io/kurs', 'images': [None]}):
            with self.subTest(cfg=cfg), patch.object(library.yaml, 'safe_load', return_value=cfg):
                with self.assertRaises(ValueError):
                    library.load_manifest()
        for change in ({'name': 123}, {'context': None}):
            cfg = library.load_manifest()
            cfg['images'][0].update(change)
            with patch.object(library.yaml, 'safe_load', return_value=cfg):
                with self.assertRaises(ValueError):
                    library.load_manifest()

    def test_workflow_choices_match_manifest(self):
        workflow = library.yaml.safe_load((library.ROOT / '.github/workflows/images.yml').read_text())
        inputs = workflow['on']['workflow_dispatch']['inputs']
        self.assertEqual(set(inputs['image']['options']),
                         {'all'} | {i['name'] for i in library.load_manifest()['images']})
        self.assertIs(inputs['publish']['default'], False)
        self.assertEqual(inputs['channel']['options'], ['candidate'])
        self.assertEqual(workflow['permissions'], {'contents': 'read'})

    def test_phpmyadmin_login_requires_database_and_logout(self):
        form = (b'<form id="login_form" action="index.php?route=/">'
                b'<input type="hidden" name="token" value="csrf&amp;token">'
                b'<input name="pma_username"><input name="pma_password"></form>')
        for body, passes in [(b'login error', False),
                             (b'<a href="?db=kurs">db</a><a href="?route=/logout">out</a>', True)]:
            first, second = MagicMock(), MagicMock()
            first.__enter__.return_value.read.return_value = form
            second.__enter__.return_value.read.return_value = body
            second.__enter__.return_value.status = 200
            with patch.object(smoke.urllib.request, 'build_opener') as factory:
                factory.return_value.open.side_effect = [first, second]
                if passes:
                    smoke.login_phpmyadmin('http://localhost:8080/')
                    request = factory.return_value.open.call_args
                    fields = smoke.urllib.parse.parse_qs(request.kwargs['data'].decode())
                    self.assertEqual(fields['token'], ['csrf&token'])
                    self.assertEqual(fields['pma_username'], ['kurs'])
                else:
                    with self.assertRaises(RuntimeError):
                        smoke.login_phpmyadmin('http://localhost:8080/')

    def test_phpmyadmin_login_rejects_missing_form(self):
        with patch.object(smoke.urllib.request, 'build_opener') as factory:
            factory.return_value.open.return_value.__enter__.return_value.read.return_value = b'error page'
            with self.assertRaises(RuntimeError):
                smoke.login_phpmyadmin('http://localhost:8080/')
            self.assertEqual(factory.return_value.open.call_count, 1)

    def test_rootful_mapping_keeps_high_host_uid(self):
        self.assertEqual(smoke.user_namespace('1001230000', rootless=False), ['--userns=host'])

    def test_cached_fixture_does_not_pull(self):
        with patch.object(smoke, 'cmd') as cmd:
            smoke.prepare_database()
            cmd.assert_called_once_with('podman', 'image', 'exists', smoke.DATABASE_FIXTURE)

    def test_missing_fixture_uses_compatible_pull(self):
        with patch.object(smoke, 'cmd', side_effect=[subprocess.CalledProcessError(1, 'exists'), None]) as cmd:
            smoke.prepare_database()
            self.assertEqual(cmd.call_args.args, ('podman', 'pull', '--platform=linux/amd64', smoke.DATABASE_FIXTURE))
            self.assertEqual(cmd.call_args.kwargs['timeout'], 600)

    def test_fixture_inspection_error_is_not_treated_as_missing(self):
        with patch.object(smoke, 'cmd', side_effect=subprocess.CalledProcessError(125, 'exists')) as cmd:
            with self.assertRaises(subprocess.CalledProcessError):
                smoke.prepare_database()
            self.assertEqual(cmd.call_count, 1)


if __name__ == '__main__':
    unittest.main()
