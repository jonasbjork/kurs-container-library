import copy
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import library
import security
import catalog


class ProductTests(unittest.TestCase):
    def test_manifest_requires_lock_and_metadata(self):
        for change in ({'platform': 'linux/arm64'}, {'surprise': True},
                       {'source': {'reference': 'nginx:latest'}}, {'command': []}):
            cfg = library.load_manifest()
            cfg['images'][0].update(change)
            with patch.object(library.yaml, 'safe_load', return_value=cfg):
                with self.assertRaises(ValueError): library.load_manifest()

    def test_credentials_and_signed_download_urls_rejected(self):
        for url in ('https://user:secret@example.com/a.tar.gz', 'https://example.com/a.tar.gz?token=secret'):
            cfg = library.load_manifest()
            item = next(i for i in cfg['images'] if i['name'] == 'wordpress')
            item['artifact']['url'] = url
            with patch.object(library.yaml, 'safe_load', return_value=cfg):
                with self.assertRaises(ValueError): library.load_manifest()

    def test_duplicate_yaml_keys_rejected(self):
        with self.assertRaises(ValueError):
            library.yaml.load('source: a\nsource: b\n', Loader=library.UniqueLoader)

    def test_source_platform_and_digest_verified(self):
        raw = json.dumps({'config': {'digest': 'sha256:' + '1' * 64}}).encode()
        ref = 'registry.example.com/repo@' + library.sha(raw)
        for architecture in ('amd64', 'arm64'):
            with patch.object(library, 'run', side_effect=[raw, json.dumps({'os': 'linux', 'architecture': architecture})]):
                if architecture == 'amd64':
                    self.assertEqual(library.source_details(ref)['digest'], library.sha(raw))
                else:
                    with self.assertRaises(ValueError): library.source_details(ref)
        with patch.object(library, 'run', return_value=raw):
            with self.assertRaises(ValueError): library.source_details('registry.example.com/repo@sha256:' + '0' * 64)

    def test_locked_indexes_are_rejected(self):
        with patch.object(library, 'run', return_value=b'{"manifests": []}'):
            with self.assertRaises(ValueError): library.source_details('registry.example.com/repo@sha256:' + '0' * 64)

    def test_tag_index_selects_exact_amd64_child(self):
        raw = b'{"config":{"digest":"sha256:123"}}'
        digest = library.sha(raw)
        index = {'manifests': [{'digest': digest, 'platform': {'os': 'linux', 'architecture': 'amd64'}},
                               {'digest': 'other', 'platform': {'os': 'linux', 'architecture': 'arm64'}}]}
        with patch.object(library, 'run', side_effect=[json.dumps(index).encode(), raw,
                          '{"os":"linux","architecture":"amd64"}']) as run:
            self.assertEqual(library.source_details('registry.example.com/repo:latest')['digest'], digest)
            self.assertEqual(run.call_args_list[1].args[-1], 'docker://registry.example.com/repo@' + digest)

    def test_mariadb_data_directory_is_outside_inherited_volume(self):
        item = next(i for i in library.load_manifest()['images'] if i['name'] == 'mariadb')
        self.assertIn('--datadir=/var/lib/kurs-mariadb/data', item['command'])
        recipe = (library.ROOT / item['context'] / 'Containerfile').read_text()
        self.assertIn('chgrp -R 0 /var/lib/kurs-mariadb', recipe)

    def test_paths_cannot_escape_repository(self):
        for path in ('../outside', '/tmp/outside', '.'):
            with self.assertRaises(ValueError): library.project_path(path)

    def test_mirror_requires_matching_assessment(self):
        item = library.load_manifest()['images'][0]
        item.update(strategy='mirror', assessment='assessments/test.json')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'assessment.json'
            path.write_text(json.dumps({'status': 'pass', 'digest': 'wrong'}))
            with patch.object(library, 'project_path', return_value=path), patch.object(library, 'import_source') as imported:
                with self.assertRaises(ValueError): library.build(item)
                imported.assert_not_called()

    def test_build_record_rejects_other_image_or_changed_inputs(self):
        item = library.load_manifest()['images'][0]
        with tempfile.TemporaryDirectory() as directory, patch.object(library, 'REPORTS', Path(directory)):
            path = Path(directory) / item['name'] / 'build.json'
            path.parent.mkdir()
            for record in ({'image_id': 'other', 'fingerprint': library.fingerprint(item)},
                           {'image_id': 'same', 'fingerprint': 'stale'}):
                library.write_json(path, record)
                with self.assertRaises(ValueError): library.require_build(item, 'same')

    def report(self, severity='CRITICAL'):
        return {'SchemaVersion': 2, 'ArtifactType': 'container_image', 'Metadata': {'ImageID': 'sha256:test'},
                'Results': [{'Target': 'os', 'Class': 'os-pkgs', 'Vulnerabilities': [{'Severity': severity,
                 'VulnerabilityID': 'CVE-2026-12345', 'PkgName': 'demo', 'InstalledVersion': '1'}]}]}

    def exception(self):
        return {'image': 'nginx', 'cve': 'CVE-2026-12345', 'package': 'demo',
                'owner': 'maintainer', 'reason': 'Documented temporary lab exception',
                'tracking': 'https://example.com/issues/1', 'expires': '2026-11-01'}

    def test_critical_policy_blocks_unfixed_and_scopes_exceptions(self):
        for name, allowed, expected in [('nginx', [], 'fail'), ('nginx', [self.exception()], 'pass'),
                                        ('python', [self.exception()], 'fail')]:
            result = security.evaluate(self.report(), name, allowed, 'sha256:test')
            self.assertEqual(result['status'], expected)
        self.assertEqual(security.evaluate(self.report('HIGH'), 'nginx', [], 'sha256:test')['status'], 'pass')

    def test_malformed_or_wrong_image_report_cannot_pass(self):
        for report in ({}, {'Results': []}, {**self.report(), 'Metadata': {'ImageID': 'other'}}):
            with self.assertRaises(ValueError): security.evaluate(report, 'nginx', [], 'sha256:test')

    def test_unsupported_os_cannot_pass_as_zero_findings(self):
        report = self.report()
        report['Metadata']['OS'] = {'Family': 'centos-stream', 'Name': '9'}
        report['Results'] = None
        self.assertEqual(security.evaluate(report, 'nginx', [], 'sha256:test')['status'], 'fail')

    def test_exceptions_expire_and_need_documentation(self):
        today = dt.date(2026, 10, 28)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'exceptions.yaml'
            path.write_text(library.yaml.safe_dump({'exceptions': [self.exception()]}))
            self.assertEqual(len(security.exceptions(path, today)), 1)
            for change in ({'expires': '2026-10-01'}, {'expires': '2028-01-01'}, {'reason': ''},
                           {'package': '*'}, {'image': '*'}, {'tracking': ''}):
                entry = {**self.exception(), **change}
                path.write_text(library.yaml.safe_dump({'exceptions': [entry]}))
                with self.assertRaises(ValueError): security.exceptions(path, today)

    def test_catalog_does_not_reuse_stale_verification(self):
        cfg = library.load_manifest()
        cfg['images'] = cfg['images'][:1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / 'reports/nginx/verification.json'
            library.write_json(report, {'smoke': 'pass', 'security': 'pass', 'fingerprint': 'stale'})
            catalog.generate(cfg, root, root / 'reports', library.fingerprint)
            data = json.loads((root / 'catalog/images.json').read_text())['images'][0]
            self.assertEqual(data['podman_status'], 'not-verified')
            self.assertIsNone(data['published'])
