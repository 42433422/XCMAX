import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { runGithubExecutor } from './github_para_executor.mjs';
import { runStrategicReport } from './strategic_report_controller.mjs';

for (const origin of ['https://xiu-ci.com', 'https://staging.xiu-ci.com']) {
  test(`ordinary report uses its own model grant and artifact at ${origin}`, async t => {
    const root = mkdtempSync(join(tmpdir(), 'strategic-controller-'));
    t.after(() => rmSync(root, { recursive: true, force: true }));
    const request = '11111111-2222-4333-8444-555555555555';
    const env = { GITHUB_ACTIONS: 'true', GITHUB_RUN_ATTEMPT: '1', GITHUB_RUN_ID: '42',
      GITHUB_SHA: 'a'.repeat(40), GITHUB_REPOSITORY: 'owner/repo', PARA_GITHUB_STAGE: 'execute',
      PARA_GITHUB_REQUEST_ID: request, PARA_GITHUB_EVIDENCE_DIR: join(root, 'evidence'),
      GITHUB_OUTPUT: join(root, 'output'), MODSTORE_PUBLIC_ORIGIN: origin,
      MODSTORE_PARA_DISPATCH_TOKEN: 'ordinary-management-identity', DEVFLEET_FORCE_OPENCODE: '1', PATH: process.env.PATH };
    const accepted = { request_id: request, kind: 'github_opencode_report', repository: 'owner/repo',
      source_sha: env.GITHUB_SHA, status: 'requested', ready: true, finished: false };
    const grant = { schema: 'strategic-remote-report/v1', kind: accepted.kind,
      request_id: request, binding_id: 'b'.repeat(32), owner_user_id: 7,
      run_id: 42, run_attempt: 1, repository: 'owner/repo', source_sha: env.GITHUB_SHA,
      deadline: new Date(Date.now() + 60000).toISOString(), task: 'Summarize support cases',
      input_data: { cases_before: 10, cases_after: 8 }, model: 'approved-model',
      model_token: 'single-task-model-grant-'.repeat(2),
      gateway_url: `${origin}/api/service/mac-control/strategic-runs/${request}/v1` };
    let completion;
    const fetchStatus = async (url, options) => {
      assert.equal(new URL(url).origin, origin);
      assert.equal(options.headers.Authorization, 'Bearer ' + env.MODSTORE_PARA_DISPATCH_TOKEN);
      if (url.endsWith('/claim')) return { ok: true, json: async () => grant };
      if (url.endsWith('/result')) {
        completion = JSON.parse(options.body);
        return { ok: true, json: async () => ({ accepted: true, status: 'pending_artifact_readback' }) };
      }
      return { ok: true, json: async () => accepted };
    };
    let launches = 0;
    const runAgent = async (cwd, prompt, options) => {
      launches += 1;
      assert.equal(options.reportOnly, true);
      assert.match(readFileSync(join(cwd, 'TASK.md'), 'utf8'), /cases_before/);
      assert.match(prompt, /Summarize support cases/);
      assert.equal(options.env.OPENCODE_API_KEY, grant.model_token);
      assert.equal(options.env.MODSTORE_PARA_DISPATCH_TOKEN, undefined);
      assert.equal(options.env.PARA_PLATFORM_GATEWAY_URL, grant.gateway_url);
      return 'Support cases decreased by 20%.';
    };
    assert.equal(await runGithubExecutor({ env, fetchStatus, verifyFeedbackIsolation: () => {},
      runReport: options => runStrategicReport({ ...options, runAgent }),
      spawnWorker: () => assert.fail('read-only report does not launch an unmetered external task') }), 0);
    assert.equal(launches, 1);
    const report = readFileSync(join(env.PARA_GITHUB_EVIDENCE_DIR, 'report.md'), 'utf8');
    assert.equal(completion.report_sha256, createHash('sha256').update(report).digest('hex'));
    assert.equal(completion.status, 'completed');
    assert.deepEqual(JSON.parse(readFileSync(join(env.PARA_GITHUB_EVIDENCE_DIR, 'execution.json'))), completion);
    assert.equal(readFileSync(env.GITHUB_OUTPUT, 'utf8'), 'strategic_report=true\n');
  });
}
