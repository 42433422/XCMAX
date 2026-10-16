"""Exercise the fixed diagnostic shell without SSH, credentials or server access."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/corp-site-diagnose.yml'


class ReadOnlyDiagnosticTest(unittest.TestCase):
    def test_fixed_workflow_and_safe_output(self):
        workflow = WORKFLOW.read_text()
        self.assertIn('group: corp-site-diagnose\n  cancel-in-progress: false', workflow)
        self.assertIn('uses: appleboy/ssh-action@v1.2.5', workflow)
        for forbidden in ('inputs:', 'schedule:', 'push:', 'StrictHostKeyChecking', 'GIT_SSH_COMMAND', 'set -x'):
            self.assertNotIn(forbidden, workflow)
        script = '\n'.join(line[12:] for line in workflow.split('          script: |\n', 1)[1].splitlines())
        subprocess.run(['bash', '-n'], input=script, text=True, check=True)
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / '.git').mkdir()
            (temp / '.git/index.lock').write_text('PRIVATE_LOCK_CONTENT')
            git = temp / 'git'
            git.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
[[ "$*" == *"rev-parse --verify "* ]] || exit 90
[[ "$GIT_OPTIONAL_LOCKS" == 0 && "$GIT_NO_LAZY_FETCH" == 1 ]] || exit 91
case "$SCENARIO" in
  failed) echo PRIVATE_ERROR >&2; exit 7;;
  invalid) echo PRIVATE_INVALID; exit 0;;
  timeout) exec sleep 3;;
esac
echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
''')
            git.chmod(0o755)
            for name, body in {'ps': '[[ "$SCENARIO" != ps_failed ]] || exit 8; echo "12 1 90 S git"; echo "13 1 2 S private-other"',
                               'lslocks': '[[ "$SCENARIO" != locks_failed ]] || exit 9; echo "12 /tmp/xcmax-site-auto-update.lock"; echo "13 /private/secret.lock"'}.items():
                executable = temp / name
                executable.write_text('#!/bin/bash\n' + body + '\n')
                executable.chmod(0o755)
            script = script.replace('ROOT=/root/XCMAX', f'ROOT={temp}').replace('2s 10s env', '0.1s 0.1s env')
            for scenario, expected in [('success', 0), ('failed', 7), ('invalid', 1), ('timeout', 124), ('ps_failed', 8), ('locks_failed', 9)]:
                with self.subTest(scenario=scenario):
                    calls = temp / 'calls'
                    calls.write_text('')
                    env = dict(os.environ, PATH=f'{temp}:{os.environ["PATH"]}', CALLS=str(calls), SCENARIO=scenario)
                    result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertNotIn('PRIVATE', result.stdout + result.stderr)
                    self.assertNotIn('private-other', result.stdout)
                    self.assertNotIn('/private/secret.lock', result.stdout)
                    self.assertEqual((temp / '.git/index.lock').read_text(), 'PRIVATE_LOCK_CONTENT')
                    self.assertTrue(all('rev-parse --verify' in line for line in calls.read_text().splitlines()))
                    self.assertEqual('Read-only snapshot complete' in result.stdout, expected == 0)
                    if expected == 0:
                        self.assertIn('HEAD=' + 'a' * 40, result.stdout)
                        self.assertIn('refs/remotes/origin/main=' + 'a' * 40, result.stdout)
                        self.assertIn('12 1 90 S git', result.stdout)


if __name__ == '__main__':
    unittest.main()
