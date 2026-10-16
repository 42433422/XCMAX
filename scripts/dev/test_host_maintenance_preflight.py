"""Execute the exact embedded probe with isolated files and mocked host commands."""
import contextlib
import io
import json
import runpy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/corp-host-maintenance-preflight.yml'
TEXT = WORKFLOW.read_text()
SHELL = '\n'.join(line[12:] for line in TEXT.split('          script: |\n', 1)[1].splitlines()) + '\n'
PROBE = SHELL.split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]

class PreflightTest(unittest.TestCase):
    def run_probe(self, setup=None, fail=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def mapped(value):
                return root / str(value).lstrip('/')
            if setup:
                setup(mapped)
            calls = []
            def command(args, **kwargs):
                calls.append(args)
                self.assertEqual(kwargs['timeout'], 15)
                self.assertNotIn('shell', kwargs)
                if fail == 'timeout':
                    raise subprocess.TimeoutExpired(args, 15, output='SECRET_TIMEOUT')
                if args[0] == fail:
                    return subprocess.CompletedProcess(args, 9, 'SECRET_STDOUT', 'SECRET_STDERR')
                return subprocess.CompletedProcess(args, 0, 'fixed metadata', '')
            stream = io.StringIO()
            with patch('pathlib.Path', mapped), patch('subprocess.run', command), contextlib.redirect_stdout(stream):
                with self.assertRaises(SystemExit) as result:
                    (root / 'probe.py').write_text(PROBE)
                    runpy.run_path(str(root / 'probe.py'))
            return result.exception.code, [json.loads(line) for line in stream.getvalue().splitlines()], calls

    def test_missing_is_unknown_not_clearance(self):
        code, records, calls = self.run_probe()
        self.assertEqual(code, 0)
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
        self.assertEqual(code, 0)
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
        self.assertEqual(len(records[-1]['value']), 3)
        self.assertNotIn('SECRET', str(records))

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
