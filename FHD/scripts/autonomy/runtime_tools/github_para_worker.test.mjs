import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runGithubWorker } from './github_para_worker.mjs';

const env = { GITHUB_ACTIONS: 'true', GITHUB_RUN_ATTEMPT: '1', GITHUB_RUN_ID: '123',
  GITHUB_REPOSITORY: 'fixture/repo', GITHUB_SHA: 'a'.repeat(40), PARA_GITHUB_REQUEST_ID: '12345678-1234-1234-1234-123456789abc',
  MODSTORE_PARA_DISPATCH_TOKEN: 'test-only-secret', PARA_CODEX_AUTH_JSON: 'private-auth' };
const state = { request_id: env.PARA_GITHUB_REQUEST_ID, run_id: 123,
  repository: 'fixture/repo', issue_number: 42, finished: false };

test('the existing Para worker stops only after management acknowledges execution; evidence excludes credentials', async () => {
  const root = mkdtempSync(join(tmpdir(), 'para-github-test-'));
  const child = new EventEmitter();
  let killed = false, spawned = false, polls = 0;
  child.kill = () => { killed = true; };
  try {
    const code = await runGithubWorker({ env: { ...env, PARA_GITHUB_EVIDENCE_DIR: root },
      fetchStatus: async (_url, options) => {
        assert.equal(options.headers.Authorization, 'Bearer test-only-secret');
        return { ok: true, json: async () => ({ ...state, finished: ++polls === 3, conclusion: 'success' }) };
      },
      spawnWorker: (_node, args, options) => {
        assert.match(args[0], /para_e2e_agent\.mjs$/);
        assert.equal(options.env.PARA_GITHUB_ISSUE_NUMBER, '42');
        assert.equal(options.env.MODSTORE_PARA_DISPATCH_TOKEN, undefined);
        assert.equal(options.env.PARA_CODEX_AUTH_JSON, undefined);
        spawned = true;
        return child;
      },
      sleep: async () => { assert.equal(killed, false); },
    });
    assert.equal(code, 0);
    assert.ok(spawned && killed);
    const evidence = readFileSync(join(root, 'execution.json'), 'utf8');
    assert.equal(JSON.parse(evidence).finished, true);
    assert.doesNotMatch(evidence, /test-only-secret|private-auth/);
    for (const invalid of [{ run_id: 999 }, { repository: 'other/repo' }, { finished: true }]) {
      await assert.rejects(runGithubWorker({ env: { ...env, PARA_GITHUB_EVIDENCE_DIR: root },
        fetchStatus: async () => ({ ok: true, json: async () => ({ ...state, ...invalid }) }),
        spawnWorker: () => assert.fail('invalid dispatch must not start Para'),
      }), /management_/);
    }
    for (const invalid of [{ source_sha: 'b'.repeat(40) }, { request_id: 'other' }, { repository: 'other/repo' }]) {
      await assert.rejects(runGithubWorker({ env: { ...env, PARA_GITHUB_EVIDENCE_DIR: root },
        fetchStatus: async () => ({ ok: true, json: async () => ({ ...state,
          benchmark_protocol: { source_sha: env.GITHUB_SHA, request_id: env.PARA_GITHUB_REQUEST_ID,
            repository: env.GITHUB_REPOSITORY, ...invalid } }) }),
        spawnWorker: () => assert.fail('changed approved source must not start Para'),
      }), /retort_frozen_source_mismatch/);
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});
