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

test('workflow guard precedes credential preparation and evidence upload always runs', () => {
  const source = readFileSync(new URL('../../../.github/workflows/para-github-worker.yml', import.meta.url), 'utf8');
  const guard = source.indexOf('- name: Block unsafe shared-identity publisher');
  assert.ok(guard > 0 && guard < source.indexOf('secrets.'));
  assert.match(source.slice(guard, source.indexOf('- uses: actions/setup-node')), /node scripts\/autonomy\/runtime_tools\/github_para_worker.mjs/);
  assert.doesNotMatch(source, /continue-on-error/);
  assert.match(source, /Retain execution evidence\n        if: always\(\)/);
});
