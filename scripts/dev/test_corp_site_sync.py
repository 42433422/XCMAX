"""No-network regression for the actual workflow's bootstrap shell."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/corp-site-deploy.yml'


class CorpSiteSyncTest(unittest.TestCase):
    def test_alternate_static_publisher_only_preserves_current_unchanged_marker(self):
        updater = (ROOT / '成都修茈科技有限公司/MODstore_deploy/scripts/xcmax-site-auto-update.sh').read_text()
        start = updater.index('guard_corp_download_marker()')
        end = updater.index('\n# Git checkout updates', start)
        guard = updater[start:end]
        self.assertIn('guard_corp_download_marker "$live_site" "$git_site" || return 1\n  log "发布官网静态', updater)
        self.assertIn('guard_corp_download_marker "$(readlink -f "$SITE_ROOT")" || return 1\n  install', updater)
        sha = 'a' * 40
        cases = ('same', 'new_source', 'live_html_changed', 'untracked_html_changed', 'head_unclear',
                 'marker_symlink', 'directory_symlink', 'source_marker', 'nginx_reload')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                live = root / 'live'
                data = live / 'site/data'
                source = root / 'git/public'
                (source / 'site/data').mkdir(parents=True)
                data.mkdir(parents=True)
                outside = root / 'external.json'
                outside.write_text('must stay untouched')
                pointer = live / 'download-release.json'
                pointer.write_text('release publisher owns this')
                marker = data / 'corp-download-deployment.json'
                (source / 'download.html').write_text('Git download page')
                (live / 'download.html').write_text('other page' if case == 'live_html_changed' else 'Git download page')
                if case == 'marker_symlink':
                    marker.symlink_to(outside)
                else:
                    marker.write_text(json.dumps({'deployed_sha': 'b' * 40 if case == 'new_source' else sha}))
                if case == 'directory_symlink':
                    data.rename(root / 'escaped')
                    data.symlink_to(root / 'escaped', target_is_directory=True)
                if case == 'source_marker':
                    (source / 'site/data' / marker.name).write_text('unsafe bootstrap')
                git = r'''
git() {
  case "$3" in
    rev-parse) printf '%s\n' "$CURRENT_HEAD" ;;
    show) printf '%s' "$COMMITTED_HTML" ;;
    *) exit 44 ;;
  esac
}
'''
                result = subprocess.run(
                    ['bash', '-c', f'set -euo pipefail\nlog() {{ :; }}\n{git}\n{guard}\nguard_corp_download_marker "$SITE_ROOT" "$SOURCE"'],
                    env=dict(
                        os.environ, SITE_ROOT=str(live.resolve()), SITE_SUBDIR='public',
                        SOURCE='' if case == 'nginx_reload' else str(source), XCMAX_ROOT=str(source.parent),
                        NEW_XCMAX_SHA=sha, CURRENT_HEAD='' if case == 'head_unclear' else sha,
                        COMMITTED_HTML='different Git version' if case == 'untracked_html_changed' else 'Git download page',
                    ),
                    capture_output=True, text=True, timeout=5,
                )
                rejected_path = case in ('directory_symlink', 'source_marker')
                self.assertEqual(result.returncode == 0, not rejected_path, result.stderr)
                self.assertEqual(marker.exists(), case == 'same' or rejected_path)
                self.assertFalse(marker.is_symlink())
                self.assertEqual(pointer.read_text(), 'release publisher owns this')
                self.assertEqual(outside.read_text(), 'must stay untouched')

    def test_deployment_marker_is_invalidated_before_copy_and_issued_only_after_smoke(self):
        workflow = WORKFLOW.read_text()
        begin = workflow.index('            deployment_marker_path()')
        copy = workflow.index('            if [ -d "${GIT_SITE}" ]', begin)
        publish = workflow.index('            SYNC_STAGE=deployment-marker', copy)
        release = workflow.index('            exec 8>&-', publish)
        self.assertLess(workflow.index('flock -w 60 8'), begin)
        self.assertLess(workflow.index('wc -c "${SITE_ROOT}/assets/xiu-ci-logo.png"'), publish)
        self.assertEqual(workflow.count('exec 8>&-'), 1)
        invalidate = '\n'.join(line[12:] for line in workflow[begin:copy].splitlines())
        issue = '\n'.join(line[12:] for line in workflow[publish:release].splitlines())
        for expression, value in {
            'github.ref': '$FIXTURE_REF', 'github.sha': '$CONTROLLER_SHA',
            'github.run_id': '1234', 'github.run_attempt': '2',
        }.items():
            issue = issue.replace('${{ ' + expression + ' }}', value)
        sha = 'a' * 40
        for case in ('main', 'non_main', 'non_main_ref', 'different_sha', 'failed_smoke', 'root_changed',
                     'head_changed', 'html_drift', 'unsafe_marker_directory', 'tracked_marker'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                live = root / 'live'
                data = live / 'site/data'
                source_data = root / 'git/site/data'
                source_data.mkdir(parents=True)
                data.mkdir(parents=True)
                marker = data / 'corp-download-deployment.json'
                marker.write_text('old marker')
                (live / 'download.html').write_text('wrong page' if case == 'html_drift' else 'official page')
                release_pointer = live / 'download-release.json'
                release_pointer.write_text('release publisher owns this')
                outside = root / 'outside'
                if case == 'unsafe_marker_directory':
                    data.rename(outside)
                    data.symlink_to(outside, target_is_directory=True)
                if case == 'tracked_marker':
                    (source_data / marker.name).write_text('source must not publish a marker')
                fixture = r'''
readlink() { printf '%s\n' "$CURRENT_ROOT"; }
git() {
  case "$3" in
    rev-parse) printf '%s\n' "$CURRENT_HEAD" ;;
    show) printf 'official page' ;;
    *) exit 44 ;;
  esac
}
'''
                smoke = 'test ! -e "$DEPLOYMENT_MARKER"\nprintf "SMOKE\\n"\n[ "$SMOKE_OK" = 1 ]'
                result = subprocess.run(
                    ['bash', '-c', f'set -euo pipefail\n{fixture}\n{invalidate}\n{smoke}\n{issue}'],
                    env=dict(
                        os.environ, LIVE_SITE=str(live), GIT_SITE=str(root / 'git'), REMOTE_ROOT=str(root / 'git'),
                        DEPLOY_SHA=sha, CONTROLLER_SHA='b' * 40 if case == 'different_sha' else sha,
                        CURRENT_HEAD='b' * 40 if case == 'head_changed' else sha,
                        CURRENT_ROOT=str(root / 'replaced' if case == 'root_changed' else live),
                        BRANCH='test' if case == 'non_main' else 'main',
                        FIXTURE_REF='refs/heads/test' if case == 'non_main_ref' else 'refs/heads/main',
                        SMOKE_OK='0' if case == 'failed_smoke' else '1',
                    ),
                    capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(result.returncode == 0, case in ('main', 'non_main', 'non_main_ref', 'different_sha'),
                                 result.stderr)
                self.assertEqual(release_pointer.read_text(), 'release publisher owns this')
                if case == 'main':
                    payload = json.loads(marker.read_text())
                    self.assertEqual(payload.pop('verified_at')[-6:], '+00:00')
                    self.assertEqual(payload, {'deployed_sha': sha, 'workflow_run_id': 1234, 'run_attempt': 2})
                    self.assertEqual(marker.stat().st_mode & 0o777, 0o644)
                    self.assertEqual(list(data.iterdir()), [marker])
                elif case == 'unsafe_marker_directory':
                    self.assertEqual((outside / marker.name).read_text(), 'old marker')
                    self.assertNotIn('SMOKE', result.stdout)
                else:
                    self.assertFalse(marker.exists())
                    if case == 'tracked_marker':
                        self.assertNotIn('SMOKE', result.stdout)

    def test_download_redirect_smoke_verifies_original_urls_and_deploy_sha(self):
        workflow = WORKFLOW.read_text()
        start = workflow.index('            # Verify the original slash URL')
        end = workflow.index('            echo "[verify] capability center', start)
        block = '\n'.join(line[12:] for line in workflow[start:end].splitlines())
        # Stand in for the existing retrying curl helper without using the network.
        fake_curl = r"""
xc_curl() {
  local output method=GET url host query target
  while [ "$#" -gt 1 ]; do
    case "$1" in
      -w) shift 2 ;;
      -o) output="$2"; shift 2 ;;
      --head) method=HEAD; shift ;;
      *) return 90 ;;
    esac
  done
  url="$1"
  printf '%s %s\n' "$method" "$url" >> "$CALLS"
  case "$url" in
    https://xiu-ci.com/download*|https://www.xiu-ci.com/download*) ;;
    *) return 91 ;;
  esac
  host="${url#https://}"
  host="${host%%/*}"
  query="${url#*\?}"
  [ "$query" = "xcmax_download_probe=${DEPLOY_SHA}" ] || return 92
  target="https://${host}/download?${query}"
  if [ "$SCENARIO" = canonical_host ]; then
    target="https://xiu-ci.com/download?${query}"
  fi
  if [ "$SCENARIO" = retry ]; then printf '000 \n'; fi
  case "$url" in
    */download/\?*)
      if [ "$host" = www.xiu-ci.com ]; then
        case "$SCENARIO" in
          canonical_slash_host|host_loop|dropped_query_second_hop|head_differs_second_hop)
            target="https://xiu-ci.com/download/?${query}" ;;
          self_loop) target="https://www.xiu-ci.com/download/?${query}" ;;
          dropped_query_host_hop) target="https://xiu-ci.com/download/" ;;
          dropped_query) target="${target%%\?*}" ;;
          foreign_target) target="https://example.invalid/download?${query}" ;;
          head_differs) if [ "$method" = HEAD ]; then target="${target%%\?*}"; fi ;;
          temporary_redirect) printf '302 %s\n' "$target"; return ;;
        esac
      elif grep -Fq "GET https://www.xiu-ci.com/download/?${query}" "$CALLS"; then
        case "$SCENARIO" in
          host_loop) target="https://www.xiu-ci.com/download/?${query}" ;;
          dropped_query_second_hop) target="${target%%\?*}" ;;
          head_differs_second_hop) if [ "$method" = HEAD ]; then target="${target%%\?*}"; fi ;;
        esac
      fi
      printf '301 %s\n' "$target"
      ;;
    *)
      case "$SCENARIO" in
        wrong_body) printf '<title>官网首页</title>' > "$output" ;;
        *) printf '<title>XCAGI 产品下载</title>' > "$output" ;;
      esac
      if [ "$SCENARIO" = final_redirect ] || \
         { [ "$SCENARIO" = final_head_differs ] && [ "$method" = HEAD ]; }; then
        printf '302 https://example.invalid/download?%s\n' "$query"
      else
        printf '200 \n'
      fi
      ;;
  esac
}
"""
        sha = 'a' * 40
        cases = {
            'direct': True, 'canonical_host': True, 'canonical_slash_host': True, 'retry': True,
            'dropped_query': False, 'foreign_target': False, 'head_differs': False,
            'temporary_redirect': False, 'wrong_body': False, 'final_redirect': False,
            'self_loop': False, 'host_loop': False,
            'dropped_query_host_hop': False, 'dropped_query_second_hop': False,
            'head_differs_second_hop': False, 'final_head_differs': False,
        }
        with tempfile.TemporaryDirectory() as directory:
            calls = Path(directory) / 'calls'
            for scenario, passed in cases.items():
                with self.subTest(scenario=scenario):
                    calls.write_text('')
                    result = subprocess.run(
                        ['bash', '-c', f'set -euo pipefail\n{fake_curl}\n{block}'],
                        env=dict(os.environ, CALLS=str(calls), DEPLOY_SHA=sha, SCENARIO=scenario),
                        capture_output=True, text=True, timeout=5,
                    )
                    self.assertEqual(result.returncode == 0, passed, result.stderr)
                    requests = calls.read_text().splitlines()
                    self.assertFalse(any('example.invalid' in call for call in requests))
                    if scenario in ('self_loop', 'host_loop'):
                        self.assertEqual(
                            requests.count(f'GET https://www.xiu-ci.com/download/?xcmax_download_probe={sha}'), 1,
                        )
                    if passed:
                        self.assertEqual(len(requests), 10 if scenario == 'canonical_slash_host' else 8)
                        for host in ('xiu-ci.com', 'www.xiu-ci.com'):
                            hops = 2 if host == 'www.xiu-ci.com' and scenario == 'canonical_slash_host' else 1
                            self.assertIn(
                                f'sha={sha} host={host} get=301 head=301 hops={hops}', result.stdout,
                            )
                    else:
                        self.assertIn(f'sha={sha}', result.stderr)

    def test_bootstrap_is_bounded_and_fail_closed(self):
        workflow = WORKFLOW.read_text()
        start = workflow.index('            # Bound each bootstrap command')
        end = workflow.index('            # This job publishes static content only;', start)
        block = '\n'.join(line[12:] for line in workflow[start:end].splitlines())
        self.assertIn('timeout --kill-after=15s 900s env GIT_TERMINAL_PROMPT=0', block)
        self.assertIn('timeout --kill-after=15s 120s git', block)
        self.assertIn('-c http.lowSpeedLimit=1024 -c http.lowSpeedTime=30', block)
        self.assertIn('command_timeout: 25m', workflow)
        self.assertNotIn('StrictHostKeyChecking', workflow)
        self.assertNotIn('GIT_SSH_COMMAND', block)
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            readlink = temp / 'readlink'
            readlink.write_text('#!/bin/bash\nprintf \'%s\\n\' "${@: -1}"\n')
            readlink.chmod(0o755)
            git = temp / 'git'
            git.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
case " $* " in
  *" fetch "*)
    test "$GIT_TERMINAL_PROMPT" = 0 || exit 91
    case "$SCENARIO" in
      fetch_error) exit 7;; fetch_timeout) exec sleep 3;;
      slow_success) for part in 1 2; do echo "receiving part $part" >&2; sleep 0.2; done;;
    esac;;
  *" reset "*) case "$SCENARIO" in reset_error) exit 8;; reset_timeout) exec sleep 3;; esac;;
  *" rev-parse "*) echo 0123456789012345678901234567890123456789;;
esac
''')
            git.chmod(0o755)
            # Only the fixture deadlines are shortened; assertions above check production values.
            cases = [('success', 0, '', '0.1s'), ('fetch_error', 7, 'fetch', '0.1s'),
                     ('fetch_timeout', 124, 'fetch', '0.1s'), ('reset_error', 8, 'reset', '0.1s'),
                     ('reset_timeout', 124, 'reset', '0.1s'),
                     # Scale 180s -> 900s to 0.2s -> 1s around the same healthy transfer.
                     ('slow_success', 124, 'fetch', '0.2s'), ('slow_success', 0, '', '1s')]
            for scenario, code, stage, fetch_limit in cases:
                with self.subTest(scenario=scenario, fetch_limit=fetch_limit):
                    script = 'set -euo pipefail\n' + block.replace('15s', '0.1s').replace('900s', fetch_limit).replace('120s', '0.1s') + '\necho PUBLISH_ALLOWED\n'
                    calls = temp / 'calls'
                    calls.write_text('')
                    env = dict(os.environ, PATH=f'{temp}:{os.environ["PATH"]}',
                               REMOTE_ROOT='/fixture', BRANCH='main', CALLS=str(calls), SCENARIO=scenario)
                    result = subprocess.run(['bash', '-c', script], env=env, capture_output=True,
                                            text=True, timeout=5)
                    self.assertEqual(result.returncode, code, result.stderr)
                    self.assertNotIn('--depth', calls.read_text())
                    self.assertNotIn('--filter', calls.read_text())
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
