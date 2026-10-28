import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import library
import okd
import catalog

D = 'sha256:' + '1' * 64
C = 'sha256:' + '2' * 64


class OkdTests(unittest.TestCase):
    def setUp(self):
        self.cfg = library.load_manifest()
        self.item = next(i for i in self.cfg['images'] if i['name'] == 'flask-lab')
        self.ref = 'quay.io/kurs/flask-lab@' + D
        self.refs = {'flask-lab': self.ref}
        self.source = {'digest': D, 'config_digest': C}

    def pod(self):
        spec = okd.workload(self.item, self.ref, 'test')['spec']['template']['spec']
        spec['securityContext'].update(runAsUser=1001000000, seLinuxOptions={'level': 's0:c1,c2'})
        return {'metadata': {'name': 'flask-lab-test', 'uid': 'pod-uid',
                            'annotations': {'openshift.io/scc': 'restricted-v2'}},
                'spec': spec, 'status': {'containerStatuses': [
                    {'ready': True, 'restartCount': 0, 'imageID': 'docker-pullable://' + self.ref}]}}

    def test_candidates_reject_tags_wrong_repo_unknown_and_duplicate_names(self):
        for refs in ({'flask-lab': 'quay.io/kurs/flask-lab:candidate-1'},
                     {'flask-lab': 'evil.example/flask-lab@' + D}, {'other': self.ref}, [],
                     {'flask-lab': self.ref + '?token=secret'}, {'flask-lab': self.ref.upper()}):
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                okd.candidates(refs, self.cfg)
        with self.assertRaises(ValueError):
            json.loads('{"a":1,"a":2}', object_pairs_hook=okd.unique_json)
        self.assertEqual(okd.candidates(self.refs, self.cfg), [self.item])

    def test_web_fixture_must_be_published_and_locked(self):
        refs = {'wordpress': 'quay.io/kurs/wordpress@' + D}
        with self.assertRaises(ValueError): okd.candidates(refs, self.cfg)
        refs['mariadb'] = 'quay.io/kurs/mariadb@' + C
        self.assertEqual(len(okd.candidates(refs, self.cfg)), 2)

    def test_every_workload_uses_controller_and_unprivileged_service_account(self):
        for item in self.cfg['images']:
            workload = okd.workload(item, 'quay.io/kurs/' + item['name'] + '@' + D, 'temp')
            self.assertEqual(workload['kind'], 'Deployment')
            pod = workload['spec']['template']['spec']
            self.assertEqual(pod['serviceAccountName'], 'kurs-smoke')
            self.assertFalse(pod['automountServiceAccountToken'])
            self.assertNotIn('runAsUser', pod['securityContext'])
            self.assertNotIn('fsGroup', pod['securityContext'])
            self.assertEqual(pod['nodeSelector']['kubernetes.io/arch'], 'amd64')
            c = pod['containers'][0]
            self.assertEqual(c['securityContext']['capabilities'], {'drop': ['ALL']})
            self.assertFalse(c['securityContext']['allowPrivilegeEscalation'])
            self.assertIn('readinessProbe', c)
            self.assertIn('startupProbe', c)
            self.assertFalse(any('value' in env and 'PASSWORD' in env['name'] for env in c['env']))

    def test_admission_requires_actual_scc_uid_security_and_digest(self):
        pod = self.pod()
        self.assertEqual(okd.admitted(pod, self.ref, self.source, '1001000000/10000')['scc'], 'restricted-v2')
        for scc in ('anyuid', 'privileged', 'restricted', None):
            bad = copy.deepcopy(pod)
            bad['metadata']['annotations']['openshift.io/scc'] = scc
            with self.assertRaises(ValueError): okd.admitted(bad, self.ref, self.source, '1001000000/10000')
        mutations = [lambda p: p['spec'].update(nodeSelector={'kubernetes.io/arch': 'arm64'}),
                     lambda p: p['spec'].update(hostNetwork=True),
                     lambda p: p['spec'].update(automountServiceAccountToken=True),
                     lambda p: p['spec']['securityContext'].update(runAsUser=0),
                     lambda p: p['spec']['securityContext'].update(runAsUser=1001010000),
                     lambda p: p['spec']['containers'][0]['securityContext'].update(allowPrivilegeEscalation=True),
                     lambda p: p['spec']['containers'][0]['securityContext'].update(seccompProfile={'type': 'Unconfined'}),
                     lambda p: p['spec']['containers'][0]['securityContext'].update(capabilities={'drop': ['ALL'], 'add': ['NET_RAW']}),
                     lambda p: p['status']['containerStatuses'][0].update(imageID='sha256:' + '3' * 64),
                     lambda p: p['status']['containerStatuses'][0].update(restartCount=1),
                     lambda p: p['status']['containerStatuses'][0].update(ready=False),
                     lambda p: p['spec'].update(volumes=[{'hostPath': {'path': '/'}}])]
        for mutation in mutations:
            bad = copy.deepcopy(pod)
            mutation(bad)
            with self.assertRaises(ValueError): okd.admitted(bad, self.ref, self.source, '1001000000/10000')
        pod['status']['containerStatuses'][0]['imageID'] = 'cri-o://' + C
        okd.admitted(pod, self.ref, self.source, '1001000000/10000')

    def test_runtime_checks_fail_on_root_capabilities_or_no_new_privs(self):
        for uid, status in [('0', 'NoNewPrivs:\t1\nCapEff:\t0000000000000000'),
                            ('1001000000', 'NoNewPrivs:\t0\nCapEff:\t0000000000000000'),
                            ('1001000000', 'NoNewPrivs:\t1\nCapEff:\t0000000000000001')]:
            with patch.object(okd, 'execute', side_effect=[uid, status]), self.assertRaises(ValueError):
                okd.runtime_checks(self.item, 'test', self.pod(), 1001000000)

    def test_exited_pod_fails_without_readiness_retry(self):
        pod = self.pod()
        pod['status']['containerStatuses'][0].update(state={'terminated': {'exitCode': 1}})
        with patch.object(okd, 'get', return_value={'items': [pod]}), patch.object(okd.time, 'sleep') as sleep:
            with self.assertRaises(ValueError): okd.wait_ready('test', 'flask-lab', 300)
            sleep.assert_not_called()

    def test_oc_never_exposes_raw_error_or_input_secret(self):
        result = subprocess.CompletedProcess([], 1, '', 'token=super-secret')
        with patch.object(okd.subprocess, 'run', return_value=result):
            with self.assertRaises(okd.OcError) as raised: okd.oc('create', '-f', '-', data={'password': 'super-secret'})
            self.assertNotIn('super-secret', str(raised.exception))
        self.assertEqual(okd.safe_reason(RuntimeError('secret-token')), 'verification-failed')

    def test_no_candidates_is_pending_and_does_not_contact_cluster(self):
        with tempfile.TemporaryDirectory() as d, patch.object(okd, 'oc') as oc:
            report = okd.verify(self.cfg, {}, Path(d) / 'result.json')
            self.assertEqual(report['status'], 'pending')
            self.assertEqual(report['reason'], 'no-published-candidates')
            oc.assert_not_called()

    def test_unavailable_cluster_overwrites_old_pass_with_pending(self):
        with tempfile.TemporaryDirectory() as d, patch.object(okd, 'oc', side_effect=okd.OcError('secret')):
            path = Path(d) / 'result.json'
            library.write_json(path, {'status': 'pass'})
            report = okd.verify(self.cfg, self.refs, path)
            self.assertEqual(report['status'], 'pending')
            self.assertEqual(json.loads(path.read_text())['status'], 'pending')
            self.assertEqual(report['images'][0]['okd_status'], 'not-verified')
            self.assertNotIn('secret', path.read_text())

    def run_mock_cluster(self, failure=None, cleanup_failure=False):
        def oc(*args, **kwargs):
            if args[:4] == ('auth', 'can-i', 'create', 'namespaces'): return 'yes'
            if args[:2] == ('create', '-f'): return ''
            raise AssertionError(args)
        def get(*args):
            if args[0] == 'clusterversion': return {'status': {'desired': {'version': '4.22.0-okd'}}}
            if args[0] == 'namespace': return {'metadata': {'annotations': {'openshift.io/sa.scc.uid-range': '1001000000/10000'}}}
            raise AssertionError(args)
        with tempfile.TemporaryDirectory() as d, patch.object(okd, 'oc', side_effect=oc), \
             patch.object(okd, 'get', side_effect=get), patch.object(okd.library, 'source_details', return_value=self.source), \
             patch.object(okd, 'verify_one', side_effect=failure, return_value={'tested_at': 'now', 'checks': ['test']}), \
             patch.object(okd, 'cleanup_namespace', side_effect=okd.OcError('secret') if cleanup_failure else None) as cleanup:
            path = Path(d) / 'result.json'
            report = okd.verify(self.cfg, self.refs, path)
            cleanup.assert_called_once_with(report['namespace'])
            self.assertNotIn('secret', path.read_text())
            return report

    def test_green_requires_functional_success_and_successful_cleanup(self):
        report = self.run_mock_cluster()
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(report['images'][0]['okd_status'], 'okd-verified')
        for report in (self.run_mock_cluster(failure=RuntimeError('secret')),
                       self.run_mock_cluster(cleanup_failure=True)):
            self.assertEqual(report['status'], 'fail')
            self.assertEqual(report['images'][0]['okd_status'], 'not-verified')

    def test_interrupt_still_removes_namespace_and_records_failure(self):
        report = self.run_mock_cluster(failure=KeyboardInterrupt())
        self.assertEqual(report['status'], 'fail')
        self.assertEqual(report['cleanup'], 'pass')
        self.assertEqual(report['reason'], 'interrupted')

    def test_failed_namespace_creation_attempt_still_checks_cleanup(self):
        with tempfile.TemporaryDirectory() as d, patch.object(okd, 'get', return_value={'status': {'desired': {'version': 'okd'}}}), \
             patch.object(okd, 'oc', side_effect=['yes', okd.OcError('timeout')]), \
             patch.object(okd.library, 'source_details', return_value=self.source), patch.object(okd, 'cleanup_namespace') as cleanup:
            report = okd.verify(self.cfg, self.refs, Path(d) / 'result.json')
            self.assertEqual(report['status'], 'fail')
            cleanup.assert_called_once()

    def test_cleanup_does_not_delete_namespace_without_run_ownership(self):
        with patch.object(okd, 'oc', return_value='{"metadata":{"labels":{}}}') as oc:
            with self.assertRaises(okd.OcError): okd.cleanup_namespace('kurs-okd-random')
            self.assertEqual(oc.call_count, 1)

    def test_source_registry_failure_precedes_namespace_creation(self):
        with tempfile.TemporaryDirectory() as d, patch.object(okd, 'get', return_value={'status': {'desired': {'version': 'okd'}}}), \
             patch.object(okd, 'oc', return_value='yes') as oc, \
             patch.object(okd.library, 'source_details', side_effect=RuntimeError('secret')), patch.object(okd, 'cleanup_namespace') as cleanup:
            report = okd.verify(self.cfg, self.refs, Path(d) / 'result.json')
            self.assertEqual(report['status'], 'fail')
            self.assertEqual(report['cleanup'], 'not-needed')
            self.assertEqual(oc.call_count, 1)
            cleanup.assert_not_called()


    def test_functional_http_and_identity_are_rechecked(self):
        pod = self.pod()
        from contextlib import nullcontext
        with patch.object(okd, 'wait_ready', return_value=pod), \
             patch.object(okd, 'runtime_checks', return_value=['file-write-read-delete']), \
             patch.object(okd, 'forward', return_value=nullcontext('http://127.0.0.1:12345')), \
             patch.object(okd.smoke, 'check_http') as http, patch.object(okd, 'get', return_value=pod):
            evidence = okd.verify_one(self.item, self.ref, self.source, 'test', '1001000000/10000', 300, 'secret')
            http.assert_called_once_with('http://127.0.0.1:12345/health', 'http')
            self.assertIn('http-content', evidence['checks'])
            with patch.object(okd.smoke, 'check_http', side_effect=RuntimeError('bad page')):
                with self.assertRaises(RuntimeError):
                    okd.verify_one(self.item, self.ref, self.source, 'test', '1001000000/10000', 300, 'secret')
            other = copy.deepcopy(pod)
            other['metadata']['uid'] = 'replacement'
            with patch.object(okd, 'get', return_value=other), self.assertRaises(ValueError):
                okd.verify_one(self.item, self.ref, self.source, 'test', '1001000000/10000', 300, 'secret')

    def test_catalog_requires_matching_published_digest_and_complete_okd_success(self):
        cfg = {**self.cfg, 'images': [self.item]}
        fp = library.fingerprint(self.item)
        publication = {'fingerprint': fp, 'image_id': C,
                       'published': {'reference': 'quay.io/kurs/flask-lab:candidate-unit', 'digest': D}}
        result = {'schema_version': 1, 'status': 'pass', 'cleanup': 'pass',
                  'cluster_version': 'okd-version', 'test_definition_sha256': D,
                  'images': [{'name': 'flask-lab', 'reference': self.ref, 'status': 'pass',
                              'okd_status': 'okd-verified', 'tested_at': 'now'}]}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            reports = root / 'reports'
            library.write_json(reports / 'flask-lab/verification.json', {'fingerprint': fp, 'image_id': C})
            library.write_json(reports / 'flask-lab/publication.json', publication)
            def generate(data):
                library.write_json(reports / 'okd/result.json', data)
                catalog.generate(cfg, root, reports, library.fingerprint)
                return json.loads((root / 'catalog/images.json').read_text())['images'][0]
            self.assertEqual(generate(result)['okd_status'], 'okd-verified')
            for change in ({'status': 'pending'}, {'cleanup': 'fail'}, {'cluster_version': None},
                           {'images': [{**result['images'][0], 'reference': 'quay.io/kurs/flask-lab@' + C}]}):
                self.assertEqual(generate({**result, **change})['okd_status'], 'not-verified')
            (reports / 'flask-lab/publication.json').unlink()
            self.assertEqual(generate(result)['okd_status'], 'not-verified')

    def test_optional_workflow_is_manual_and_independent(self):
        workflow = library.yaml.safe_load((library.ROOT / '.github/workflows/okd.yml').read_text())
        self.assertEqual(set(workflow['on']), {'workflow_dispatch'})
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        job = workflow['jobs']['okd']
        self.assertEqual(job['environment'], 'okd')
        self.assertNotIn('needs', job)
        text = (library.ROOT / '.github/workflows/okd.yml').read_text()
        self.assertNotIn('QUAY_TOKEN', text)
        self.assertNotIn('library.py publish', text)
        main = (library.ROOT / '.github/workflows/images.yml').read_text()
        self.assertNotIn('okd.py', main)
        self.assertNotIn('OKD_KUBECONFIG', main)


    def test_all_sql_commands_require_the_written_value(self):
        kernel = 'NoNewPrivs:\t1\nCapEff:\t0000000000000000'
        for kind in ('postgres', 'mysql', 'mariadb', 'wordpress', 'phpmyadmin'):
            item = next(i for i in self.cfg['images'] if i['test'] == kind)
            for result in ('42', '0'):
                with patch.object(okd, 'execute', side_effect=['1001000000', kernel, '', result]) as execute:
                    if result == '42':
                        checks = okd.runtime_checks(item, 'test', self.pod(), 1001000000)
                        self.assertIn('sql-write-read', checks)
                    else:
                        with self.assertRaises(ValueError):
                            okd.runtime_checks(item, 'test', self.pod(), 1001000000)
                    command = execute.call_args.args
                    self.assertNotIn('testpass', ' '.join(map(str, command)))
                    if 'sh' in command:
                        subprocess.run(['sh', '-n', '-c', command[-1]], check=True, capture_output=True)

    def test_cli_pending_succeeds_but_bad_input_fails_and_invalidates_old_pass(self):
        with tempfile.TemporaryDirectory() as d:
            input_path, output = Path(d) / 'candidates.json', Path(d) / 'result.json'
            args = ['okd.py', '--candidates', str(input_path), '--output', str(output)]
            for contents, status, code in [('{}', 'pending', 0), ('{"unknown":"tag"}', 'fail', 1)]:
                input_path.write_text(contents)
                library.write_json(output, {'status': 'pass'})
                with patch.object(sys, 'argv', args), patch.object(okd, 'oc') as oc:
                    with self.assertRaises(SystemExit) as exit:
                        okd.main()
                    self.assertEqual(exit.exception.code, code)
                    self.assertEqual(json.loads(output.read_text())['status'], status)
                    oc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
