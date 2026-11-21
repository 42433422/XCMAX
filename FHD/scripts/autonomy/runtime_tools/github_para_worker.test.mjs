import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runGithubWorker } from './github_para_worker.mjs';

test('GitHub shared identity fails closed before network/model launch and emits precise secret-free evidence', async () => {
  const root = mkdtempSync(join(tmpdir(), 'para-github-test-'));
  try {
    for (const privileges of [{ GH_TOKEN: 'fake-publish' }, { CI_COMMIT_TOKEN: 'fake-admin' }, {}]) {
      await assert.rejects(runGithubWorker({ env: { ...privileges, GITHUB_RUN_ID: '123',
        PARA_GITHUB_REQUEST_ID: 'fixture-request', PARA_GITHUB_EVIDENCE_DIR: root,
        MODSTORE_PARA_DISPATCH_TOKEN: 'fake-management', CODEX_API_KEY: 'fake-model',
        PARA_ISOLATED_PUBLISHER: '1' }, // no caller-controlled bypass
        fetchStatus: () => assert.fail('must not contact management'),
        spawnWorker: () => assert.fail('must not start a model'),
      }), /^Error: blocked_isolated_publisher_required$/);
      const raw = readFileSync(join(root, 'execution.json'), 'utf8');
      const evidence = JSON.parse(raw);
      assert.equal(evidence.request_id, 'fixture-request');
      assert.equal(evidence.run_id, '123');
      assert.equal(evidence.finished, true);
      assert.equal(evidence.conclusion, 'failure');
      assert.equal(evidence.status, 'blocked');
      assert.equal(evidence.reason, 'blocked_isolated_publisher_required');
      assert.doesNotMatch(raw, /fake-publish|fake-admin|fake-management|fake-model/);
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('workflow isolates the publisher in a fresh hosted job and uses trusted entry points', () => {
  const source = readFileSync(new URL('../../../.github/workflows/para-github-worker.yml', import.meta.url), 'utf8');
  const execute = source.split('  employee-workspace:')[1].split('  publish-candidate:')[0];
  const publisher = source.split('  publish-candidate:')[1].split('  resume-verification:')[0];
  const resume = source.split('  resume-verification:')[1].split('  independent-verification:')[0];
  const runners = stage => stage.split('\n').map(line => line.trim()).filter(line => line.startsWith('runs-on:'));
  for (const stage of [execute, resume]) {
    assert.deepEqual(runners(stage), [
      "runs-on: ${{ vars.DEVFLEET_FORCE_OPENCODE == '1' && 'ubuntu-22.04' || 'ubuntu-24.04' }}",
    ]);
    assert.doesNotMatch(stage, /CI_COMMIT_TOKEN|GH_TOKEN|contents: write/);
    assert.match(stage, /ref: \$\{\{ github.sha \}\}/);
    assert.match(stage, /persist-credentials: false/);
    assert.match(stage, /github_para_executor.mjs/);
  }
  assert.match(publisher, /needs: employee-workspace/);
  assert.deepEqual(runners(publisher), ['runs-on: ubuntu-24.04']);
  assert.match(publisher, /ref: \$\{\{ github.sha \}\}/);
  assert.match(publisher, /publish_para_candidate.py/);
  assert.doesNotMatch(publisher, /CODEX_API_KEY|PARA_CODEX_AUTH|DEVFLEET_DEVICE_TOKEN|node_modules|checkout.*candidate/);
  assert.match(resume, /needs: publish-candidate/);
  for (const use of source.matchAll(/uses: actions\/[a-z-]+@([^\s]+)/g)) assert.match(use[1], /^[0-9a-f]{40}$/);
  assert.doesNotMatch(source, /continue-on-error/);
  assert.match(source, /Retain execution evidence\n        if: always\(\)/);
});
