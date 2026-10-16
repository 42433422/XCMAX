"""No-network regression for the actual workflow's bootstrap shell."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/corp-site-deploy.yml'


class CorpSiteSyncTest(unittest.TestCase):
    def test_bootstrap_is_bounded_and_fail_closed(self):
        workflow = WORKFLOW.read_text()
        start = workflow.index('            # Bound each bootstrap command')
        end = workflow.index('            # Always republish', start)
        block = '\n'.join(line[12:] for line in workflow[start:end].splitlines())
        self.assertIn('timeout --kill-after=15s 180s env GIT_TERMINAL_PROMPT=0', block)
        self.assertIn('timeout --kill-after=15s 120s git', block)
        self.assertIn('-c http.lowSpeedLimit=1024 -c http.lowSpeedTime=30', block)
        self.assertNotIn('StrictHostKeyChecking', workflow)
        self.assertNotIn('GIT_SSH_COMMAND', block)
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            git = temp / 'git'
            git.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
case " $* " in
  *" fetch "*)
    test "$GIT_TERMINAL_PROMPT" = 0 || exit 91
    case "$SCENARIO" in fetch_error) exit 7;; fetch_timeout) exec sleep 3;; esac;;
  *" reset "*) case "$SCENARIO" in reset_error) exit 8;; reset_timeout) exec sleep 3;; esac;;
  *" rev-parse "*) echo 0123456789012345678901234567890123456789;;
esac
''')
            git.chmod(0o755)
            # Only the fixture deadlines are shortened; assertions above check production values.
            script = 'set -euo pipefail\n' + block.replace('15s', '0.1s').replace('180s', '0.1s').replace('120s', '0.1s') + '\necho PUBLISH_ALLOWED\n'
            for scenario, code, stage in [('success', 0, ''), ('fetch_error', 7, 'fetch'),
                                           ('fetch_timeout', 124, 'fetch'), ('reset_error', 8, 'reset'), ('reset_timeout', 124, 'reset')]:
                with self.subTest(scenario=scenario):
                    calls = temp / 'calls'
                    calls.write_text('')
                    env = dict(os.environ, PATH=f'{temp}:{os.environ["PATH"]}',
                               REMOTE_ROOT='/fixture', BRANCH='main', CALLS=str(calls), SCENARIO=scenario)
                    result = subprocess.run(['bash', '-c', script], env=env, capture_output=True,
                                            text=True, timeout=5)
                    self.assertEqual(result.returncode, code, result.stderr)
                    if code:
                        self.assertIn(f'stage={stage} exit={code}', result.stderr)
                        self.assertNotIn('PUBLISH_ALLOWED', result.stdout)
                        if stage == 'fetch':
                            self.assertNotIn(' reset ', calls.read_text())
                    else:
                        self.assertIn('exact server worktree sha=', result.stdout)
                        self.assertIn('PUBLISH_ALLOWED', result.stdout)
                        self.assertIn('fetch --progress origin main', calls.read_text())

    def test_updater_second_sync_does_not_fall_through_after_timeout(self):
        updater = (ROOT / '成都修茈科技有限公司/MODstore_deploy/scripts/xcmax-site-auto-update.sh').read_text()
        block = updater[updater.index('git_step() {'):updater.index('# Vite build')]
        self.assertIn('fetch 180s fetch --progress', block)
        self.assertIn('merge 120s merge --ff-only', block)
        self.assertIn('reset 120s reset --hard', block)
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / '.git').mkdir()
            git = temp / 'git'
            git.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
case " $* " in
  *" fetch "*) case "$SCENARIO" in fetch_error) exit 7;; fetch_timeout) exec sleep 3;; esac;;
  *" merge "*) case "$SCENARIO" in merge_timeout) exec sleep 3;; merge_kill) trap '' TERM; exec sleep 3;; merge_group) trap '' TERM; sleep 3 & echo $! > "$CHILD_PID"; wait;; fallback|reset_error|reset_timeout) exit 1;; esac;;
  *" reset "*) case "$SCENARIO" in reset_error) exit 8;; reset_timeout) exec sleep 3;; esac;;
  *" rev-parse "*)
    case "$SCENARIO" in identity_error) exit 9;; identity_empty) exit 0;; esac
    if [[ "$SCENARIO" == unchanged || " $* " == *" origin/main "* ]]; then
      echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    else echo bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb; fi;;
esac
''')
            git.chmod(0o755)
            script = 'set -euo pipefail\nlog() { :; }\n' + block.replace('15s', '0.1s').replace('180s', '0.1s').replace('120s', '0.1s')
            script += '\nif sha=$(git_sync_repo "$REMOTE_ROOT" fixture); then echo "PUBLISH_ALLOWED:$sha"; else exit $?; fi\n'
            cases = [('success', 0), ('unchanged', 0), ('fallback', 0), ('identity_error', 9), ('identity_empty', 1), ('fetch_error', 7), ('fetch_timeout', 124),
                     ('merge_timeout', 124), ('merge_kill', 137), ('merge_group', 137), ('reset_error', 8), ('reset_timeout', 124)]
            for scenario, code in cases:
                with self.subTest(scenario=scenario):
                    calls = temp / 'calls'
                    calls.write_text('')
                    env = dict(os.environ, PATH=f'{temp}:{os.environ["PATH"]}', REMOTE_ROOT=str(temp),
                               BRANCH='main', CALLS=str(calls), SCENARIO=scenario, LOG=str(temp / 'sync.log'),
                               XCMAX_GIT_RESET_HARD='1', CHILD_PID=str(temp / 'child.pid'))
                    result = subprocess.run(['bash', '-c', script], env=env, capture_output=True,
                                            text=True, timeout=5)
                    self.assertEqual(result.returncode, code, result.stderr)
                    if code:
                        self.assertNotIn('PUBLISH_ALLOWED', result.stdout)
                        if not scenario.startswith('identity_'):
                            self.assertIn(f'exit={code}', result.stderr)
                    else:
                        self.assertEqual(result.stdout.strip(), 'PUBLISH_ALLOWED:' + 'a' * 40)
                    if scenario in ('fetch_error', 'fetch_timeout', 'merge_timeout', 'merge_kill', 'merge_group', 'identity_error', 'identity_empty', 'unchanged'):
                        self.assertNotIn(' reset ', calls.read_text())
                    if scenario == 'merge_group':
                        pid = (temp / 'child.pid').read_text().strip()
                        state = Path(f'/proc/{pid}/stat')
                        if state.exists():
                            self.assertEqual(state.read_text().split(') ')[1].split()[0], 'Z')


if __name__ == '__main__':
    unittest.main()
