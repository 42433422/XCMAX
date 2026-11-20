import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runGithubExecutor } from './github_para_executor.mjs';

const identity = { request_id: '11111111-2222-4333-8444-555555555555', run_id: '123', repository: 'owner/repo', issue_number: 42, finished: false };
function environment(root, stage = 'execute') {
  return { GITHUB_ACTIONS: 'true', GITHUB_RUN_ATTEMPT: '1', GITHUB_RUN_ID: '123', GITHUB_SHA: 'a'.repeat(40),
    GITHUB_REPOSITORY: 'owner/repo', PARA_GITHUB_STAGE: stage, PARA_GITHUB_REQUEST_ID: identity.request_id,
    PARA_GITHUB_CANDIDATE_DIR: join(root, 'candidate'), PARA_GITHUB_EVIDENCE_DIR: join(root, 'evidence'), MODSTORE_PARA_DISPATCH_TOKEN: 'management' };
}
test('execution only hands off the original acknowledged candidate and keeps delivery unfinished', async () => {
  const root = mkdtempSync(join(tmpdir(), 'para-executor-'));
  try {
    const env = environment(root), manifest = { commit_sha: 'b'.repeat(40), task_id: 'task-1' };
    mkdirSync(env.PARA_GITHUB_CANDIDATE_DIR); writeFileSync(join(env.PARA_GITHUB_CANDIDATE_DIR, 'manifest.json'), JSON.stringify(manifest));
    const agent = new EventEmitter(); let stopped = 0; agent.kill = () => { stopped += 1; };
    const result = await runGithubExecutor({ env, fetchStatus: async () => ({ ok: true, json: async () => ({ ...identity, publication_candidate: manifest }) }),
      spawnWorker: (_exe, _args, opts) => { assert.equal(opts.env.MODSTORE_PARA_DISPATCH_TOKEN, undefined); return agent; } });
    assert.equal(result, 0); assert.equal(stopped, 1);
    const evidence = JSON.parse(readFileSync(join(env.PARA_GITHUB_EVIDENCE_DIR, 'execution.json')));
    assert.equal(evidence.finished, false); assert.equal(evidence.status, 'awaiting_publication');
    await assert.rejects(runGithubExecutor({ env: { ...env, GH_TOKEN: 'publish' },
      fetchStatus: () => assert.fail('no network'), spawnWorker: () => assert.fail('no model') }), /must_not_receive/);
    await assert.rejects(runGithubExecutor({ env, fetchStatus: async () => ({ ok: true, json: async () => ({ ...identity, publication_candidate: { ...manifest, task_id: 'other' } }) }),
      spawnWorker: () => agent }), /receipt_mismatch/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
test('resume waits for the original team and returns failure for failed verification', async () => {
  const root = mkdtempSync(join(tmpdir(), 'para-resume-'));
  try {
    for (const conclusion of ['success', 'failure']) {
      let n = 0; const agent = new EventEmitter(); agent.kill = () => {};
      const result = await runGithubExecutor({ env: environment(root, 'resume'),
        fetchStatus: async () => ({ ok: true, json: async () => ({ ...identity, finished: ++n > 1, conclusion }) }), spawnWorker: () => agent });
      assert.equal(result, conclusion === 'success' ? 0 : 1);
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('platform execution uses the admitted route and limited gateway credential', async () => {
  const root = mkdtempSync(join(tmpdir(), 'para-platform-'));
  try {
    const env = { ...environment(root, 'resume'), PARA_PLATFORM_POOL: '1',
      PARA_PLATFORM_GATEWAY_KEYS_JSON: JSON.stringify({
        'coding-route': 'fixture-platform-key', 'backup-route': 'fixture-backup-key',
        'unapproved-route': 'fixture-unused-key',
      }), CODEX_API_KEY: 'fixture-legacy-key' };
    const stub = (data) => async () => ({ ok: true, json: async () => data });
    await assert.rejects(runGithubExecutor({ env, fetchStatus: stub(identity),
      spawnWorker: () => assert.fail('must not start without model admission') }), /platform_model_allocation/);
    let reads = 0;
    const model_allocation = { status: 'admitted', model: 'coding-route', approved_models: ['coding-route', 'backup-route'] };
    await assert.rejects(runGithubExecutor({ env, fetchStatus: stub({ ...identity, model_allocation: { ...model_allocation, approved_models: ['other'] } }),
      spawnWorker: () => assert.fail('must reject a list inconsistent with the approved primary') }), /platform_model_allocation/);
    const agent = new EventEmitter(); agent.kill = () => {};
    const result = await runGithubExecutor({ env,
      fetchStatus: () => stub({ ...identity, finished: ++reads > 1, conclusion: 'success', model_allocation })(),
      spawnWorker: (_exe, _args, { env: child }) => {
        assert.equal(child.CODEX_API_KEY, 'fixture-platform-key');
        assert.equal(child.PARA_PLATFORM_GATEWAY_KEY, undefined);
        assert.equal(child.PARA_PLATFORM_GATEWAY_KEYS_JSON, undefined);
        assert.deepEqual(JSON.parse(child.PARA_PLATFORM_APPROVED_KEYRING), {
          'coding-route': 'fixture-platform-key', 'backup-route': 'fixture-backup-key',
        });
        assert.equal(child.PARA_PLATFORM_MODEL, 'coding-route');
        assert.equal(child.PARA_PLATFORM_MODEL_CANDIDATES, 'coding-route,backup-route');
        return agent;
      },
    });
    assert.equal(result, 0);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
