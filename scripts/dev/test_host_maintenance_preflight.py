"""Execute the exact embedded probe with isolated files and mocked host commands."""
import contextlib
import io
import hashlib
import json
import runpy
from pathlib import Path
import subprocess
import sys
import selectors
import time
import tempfile
import unittest
from unittest.mock import patch
WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/corp-host-maintenance-preflight.yml'
TEXT = WORKFLOW.read_text()
SHELL = '\n'.join(line[12:] for line in TEXT.split('          script: |\n', 1)[1].splitlines()) + '\n'
PROBE = SHELL.split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]

class PreflightTest(unittest.TestCase):
    def run_probe(self, setup=None, fail=None, tool_missing=False, command_hook=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def mapped(value):
                return root / str(value).lstrip('/')
            if setup:
                setup(mapped)
            calls = []
            def command(args, **kwargs):
                calls.append(args)
                if command_hook:
                    override = command_hook(args)
                    if override is not None:
                        return override
                self.assertEqual(kwargs['timeout'], 15)
                self.assertNotIn('shell', kwargs)
                if fail == 'timeout':
                    raise subprocess.TimeoutExpired(args, 15, output='SECRET_TIMEOUT')
                if args[-1] == '--version':
                    return subprocess.CompletedProcess(args, 0, Path(args[0]).name + ' (PostgreSQL) 16.4 (vendor build)\n', '')
                if Path(args[0]).name == fail:
                    return subprocess.CompletedProcess(args, 9, b'SECRET_STDOUT', b'SECRET_STDERR')
                return subprocess.CompletedProcess(args, 0, 'fixed metadata', '')
            real_popen = subprocess.Popen
            def validator_process(args, **kwargs):
                result = command(args, timeout=15)
                detail = result.stderr or b''
                if isinstance(detail, str):
                    detail = detail.encode()
                script = f'import os, sys; os.write(2, {detail!r}); sys.exit({result.returncode})'
                return real_popen([sys.executable, '-c', script], **kwargs)
            stream = io.StringIO()
            with patch('pathlib.Path', mapped), patch('subprocess.run', command), patch('subprocess.Popen', validator_process), patch('shutil.which', side_effect=lambda tool, **kw: None if tool_missing else '/usr/bin/' + tool), contextlib.redirect_stdout(stream):
                with self.assertRaises(SystemExit) as result:
                    (root / 'probe.py').write_text(PROBE)
                    runpy.run_path(str(root / 'probe.py'))
            return result.exception.code, [json.loads(line) for line in stream.getvalue().splitlines()], calls

    def test_missing_is_unknown_not_clearance(self):
        code, records, calls = self.run_probe()
        self.assertEqual(code, 1)
        self.assertTrue(any(r['value'] == 'missing' for r in records))
        self.assertIn('not maintenance clearance', str(records))
        self.assertEqual({c[0] for c in calls}, {'uname', 'rpm', 'grubby', 'df', 'systemctl'})
        self.assertTrue(all(c[1] == 'show' for c in calls if c[0] == 'systemctl'))

    def test_bounded_allowlisted_metadata(self):
        def setup(path):
            directory = path('/var/backups/xcmax/daily/20261016')
            directory.mkdir(parents=True)
            (directory / 'configs.tar.gz').write_text('SECRET_CONFIGURATION')
            (directory / 'customer-secret.txt').write_text('SECRET_DATA')
            state = path('/var/lib/xcmax-ops/state')
            state.mkdir(parents=True)
            (state / 'backup_last_success').write_text('1792173600\n')
            env = path('/etc/xcmax-dr-auto-failover.env')
            env.parent.mkdir(parents=True)
            env.write_text('PASSWORD=SECRET_PASSWORD\nOPS_DR_AUTO_FAILOVER_ENABLED=0\n')
        code, records, _ = self.run_probe(setup)
        self.assertEqual(code, 1)
        self.assertNotIn('SECRET', str(records))
        self.assertNotIn('customer-secret', str(records))
        self.assertTrue(any(r['value'] == '1792173600' for r in records))
        self.assertTrue(any(r['value'] == '0' for r in records))

    def test_command_failure_visible_without_raw_output(self):
        code, records, _ = self.run_probe(fail='rpm')
        self.assertEqual(code, 1)
        self.assertNotIn('SECRET', str(records))
        self.assertIn('installed_kernels', str(records[-1]))

    def test_timeout_and_unsafe_state_are_visible(self):
        code, records, _ = self.run_probe(fail='timeout')
        self.assertEqual(code, 1)
        self.assertNotIn('SECRET', str(records))
        def setup(path):
            import os
            state = path('/var/lib/xcmax-ops/state')
            state.mkdir(parents=True)
            os.mkfifo(state / 'backup_last_success')
            (state / 'offsite_ssh_last_success').symlink_to('/etc/passwd')
            env = path('/etc/xcmax-dr-auto-failover.env')
            env.parent.mkdir(parents=True)
            env.write_text('SECRET' * 3000)
        code, records, _ = self.run_probe(setup)
        self.assertEqual(code, 1)
        self.assertEqual(len(records[-1]['value']), 4)
        self.assertNotIn('SECRET', str(records))

    def backup_fixture(self, path):
        directory = path('/var/backups/xcmax/daily/20261016')
        directory.mkdir(parents=True)
        lock = path('/tmp/xcmax-backup.lock')
        lock.parent.mkdir(parents=True)
        lock.touch()
        names = ('fhd_pg.dump', 'modstore_pg.dump', 'payment_pg.dump',
                 'modstore_sqlite.db.gz', 'configs.tar.gz')
        manifest = []
        for name in names:
            content = b'PGDMP\x01\x0f\x00PRIVATE_BACKUP_CONTENT'
            (directory / name).write_bytes(content)
            manifest.append(hashlib.sha256(content).hexdigest() + '  ./' + name)
        (directory / 'MANIFEST.txt').write_text('\n'.join(manifest) + '\n')
        return directory

    def test_backup_integrity_success_is_narrow(self):
        code, records, calls = self.run_probe(self.backup_fixture)
        self.assertEqual(code, 0)
        integrity = next(r['value'] for r in records if r['check'] == 'backup_integrity')
        self.assertEqual(integrity['status'], 'verified')
        self.assertEqual(integrity['reason'], 'hashes_and_archive_readability_only')
        self.assertNotIn('PRIVATE_BACKUP_CONTENT', str(records))
        self.assertEqual(sum(Path(c[0]).name in ('pg_restore', 'gzip', 'tar') and c[-1] != '--version' for c in calls), 5)

    def test_invalid_backup_is_never_verified(self):
        for case in ('checksum', 'extra_path', 'duplicate', 'missing', 'symlink', 'stale'):
            with self.subTest(case=case):
                def setup(path):
                    import os
                    directory = self.backup_fixture(path)
                    manifest = directory / 'MANIFEST.txt'
                    if case == 'checksum':
                        (directory / 'fhd_pg.dump').write_bytes(b'CHANGED')
                    elif case == 'extra_path':
                        manifest.write_text(manifest.read_text() + '0' * 64 + '  ../../secret\n')
                    elif case == 'duplicate':
                        manifest.write_text(manifest.read_text() * 2)
                    elif case == 'missing':
                        (directory / 'configs.tar.gz').unlink()
                    elif case == 'symlink':
                        (directory / 'configs.tar.gz').unlink()
                        (directory / 'configs.tar.gz').symlink_to('/etc/passwd')
                    else:
                        os.utime(manifest, (1, 1))
                code, records, _ = self.run_probe(setup)
                self.assertEqual(code, 1)
                self.assertIn('backup_integrity', records[-1]['value'])
                self.assertNotIn('PRIVATE_BACKUP_CONTENT', str(records))

    def test_missing_or_failed_validator_is_unknown(self):
        for missing, fail in ((True, None), (False, 'pg_restore'), (False, 'gzip'), (False, 'tar')):
            code, records, _ = self.run_probe(self.backup_fixture, fail=fail, tool_missing=missing)
            self.assertEqual(code, 1)
            integrity = next(r['value'] for r in records if r['check'] == 'backup_integrity')
            self.assertEqual(integrity['status'], 'unknown')
            self.assertEqual(integrity['reason'], 'archive_validator_failed_or_unknown')
            results = [r['value'] for r in records if r['check'] == 'archive_validator']
            self.assertEqual(len(results), 5)
            self.assertTrue(all(r['category'] == 'missing_tool' if missing else r['exitcode'] == 9
                                for r in results if missing or r['tool'] == fail))
            self.assertNotIn('SECRET', str(records))

    def test_writer_busy_or_changed_snapshot_is_unknown(self):
        with patch('fcntl.flock', side_effect=BlockingIOError):
            code, records, _ = self.run_probe(self.backup_fixture)
        self.assertEqual(code, 1)
        self.assertIn('backup_writer_busy', str(records))
        def change_snapshot(args):
            if Path(args[0]).name in ('pg_restore', 'gzip', 'tar') and args[-1] != '--version':
                manifest = Path(args[-1]).parent / 'MANIFEST.txt'
                manifest.write_text('CHANGED_DURING_CHECK')
        code, records, _ = self.run_probe(self.backup_fixture, command_hook=change_snapshot)
        self.assertEqual(code, 1)
        self.assertIn('snapshot_changed_during_check', str(records))

    def test_pg_diagnostics_are_allowlisted_and_independent(self):
        cases = ((b'unsupported version (1.16) in file header SECRET', 'unsupported_version'),
                 (b'did not find magic string SECRET', 'bad_magic'),
                 (b'Permission denied SECRET', 'permission'), (b'SECRET OTHER ERROR', 'other'))
        for detail, category in cases:
            with self.subTest(category=category):
                def failure(args):
                    if Path(args[0]).name == 'pg_restore' and args[-1] != '--version':
                        return subprocess.CompletedProcess(args, 1, b'SECRET_SQL', detail)
                code, records, calls = self.run_probe(self.backup_fixture, command_hook=failure)
                self.assertEqual(code, 1)
                results = [r['value'] for r in records if r['check'] == 'archive_validator']
                self.assertEqual([r['category'] for r in results], [category] * 3 + ['ok', 'ok'])
                self.assertEqual([r['exitcode'] for r in results], [1, 1, 1, 0, 0])
                headers = [r['value'] for r in records if r['check'] == 'archive_format']
                self.assertEqual(len(headers), 3)
                self.assertTrue(all(r['version'] == [1, 15, 0] for r in headers))
                versions = [r['value'] for r in records if r['check'].endswith('_host_candidate')]
                self.assertEqual([r['version'] for r in versions], ['16.4', '16.4'])
                self.assertEqual([r['path'] for r in versions], ['/usr/bin/pg_restore', '/usr/bin/pg_dump'])
                self.assertNotIn('SECRET', str(records))
                self.assertNotIn('PRIVATE_BACKUP_CONTENT', str(records))
                self.assertNotIn('vendor build', str(records))

    def test_version_and_validator_exceptions_stay_unknown(self):
        for failure in ('timeout', 'execution_error', 'bad_version'):
            def hook(args):
                if Path(args[0]).name != 'pg_restore':
                    return None
                if failure == 'timeout':
                    raise subprocess.TimeoutExpired(args, 15, output=b'SECRET', stderr=b'SECRET')
                if failure == 'execution_error':
                    raise PermissionError('SECRET')
                if args[-1] == '--version':
                    return subprocess.CompletedProcess(args, 0, 'SECRET INVALID VERSION', 'SECRET')
            code, records, _ = self.run_probe(self.backup_fixture, command_hook=hook)
            version = next(r['value'] for r in records if r['check'] == 'pg_restore_host_candidate')
            self.assertEqual(version['version'], 'unknown')
            results = [r['value'] for r in records if r['check'] == 'archive_validator']
            self.assertEqual(len(results), 5)
            self.assertEqual([r['category'] for r in results][-2:], ['ok', 'ok'])
            self.assertEqual(code, 0 if failure == 'bad_version' else 1)
            self.assertNotIn('SECRET', str(records))

    def test_archive_header_never_emits_unrecognized_bytes(self):
        for content, version in ((b'SECRET_BACKUP', None), (b'PGDMP\x01\x00\x04SECRET', [1, 0, 0])):
            def setup(path):
                directory = self.backup_fixture(path)
                target = directory / 'fhd_pg.dump'
                old_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                target.write_bytes(content)
                manifest = directory / 'MANIFEST.txt'
                manifest.write_text(manifest.read_text().replace(old_hash, hashlib.sha256(content).hexdigest(), 1))
            _, records, _ = self.run_probe(setup)
            header = next(r['value'] for r in records if r['check'] == 'archive_format')
            self.assertEqual(header['version'], version)
            self.assertNotIn('SECRET', str(records))

    def test_real_validator_stderr_capture_is_bounded(self):
        imports = 'import os, subprocess, selectors, time\n'
        function = 'def run_validator' + PROBE.split('def run_validator', 1)[1].split('def validate_archive', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            module = Path(directory) / 'capture.py'
            module.write_text(imports + function)
            capture = runpy.run_path(str(module))['run_validator']
            args = [sys.executable, '-c', "import os,sys; os.write(2, b'x' * 1048576); sys.exit(7)"]
            code, detail = capture(args)
            self.assertEqual(code, 7)
            self.assertEqual(detail, b'x' * 4096)
            selector = selectors.DefaultSelector()
            select = selector.select
            first = True
            def delayed_select(timeout):
                nonlocal first
                if first:
                    first = False
                    time.sleep(0.1)
                    return []
                return select(timeout)
            with patch('selectors.DefaultSelector', return_value=selector), patch.object(selector, 'select', delayed_select):
                code, detail = capture([sys.executable, '-c', "import os; os.write(2, b'unsupported version')"])
            self.assertEqual(detail, b'unsupported version')
            with patch('time.monotonic', side_effect=[0, 16]):
                with self.assertRaises(subprocess.TimeoutExpired):
                    capture([sys.executable, '-c', 'import time; time.sleep(60)'])

    def test_real_df_inode_arguments(self):
        _, _, calls = self.run_probe()
        args = next(c for c in calls if c[0] == 'df' and 'itotal' in ' '.join(c))
        subprocess.run(args[:-2] + ['/'], capture_output=True, text=True, check=True)

    def test_shell_and_dispatch_contract(self):
        subprocess.run(['bash', '-n'], input=SHELL, text=True, check=True)
        compile(PROBE, str(WORKFLOW), 'exec')
        self.assertIn('workflow_dispatch:\npermissions:', TEXT)
        self.assertIn('cancel-in-progress: false', TEXT)
        self.assertNotIn('inputs.', TEXT)
        self.assertNotIn('StrictHostKeyChecking', TEXT)
        self.assertNotIn('source ', SHELL)

if __name__ == '__main__':
    unittest.main()
