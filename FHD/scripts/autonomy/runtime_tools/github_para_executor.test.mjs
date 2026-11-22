import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runGithubExecutor } from './github_para_executor.mjs';
import { modelChildEnv } from './credential_vault.mjs';
import { openCodePlatformConfig, OPENCODE_CREDENTIAL_ISOLATION } from './opencode_agent.mjs';
import { bindWorkspaceTask, requireWorkspaceCandidate } from './strategic_workspace_controller.mjs';

const identity = { request_id: '11111111-2222-4333-8444-555555555555', run_id: '123', repository: 'owner/repo', issue_number: 42, finished: false };

for (const kind of ['customer_feedback_repair', 'training_candidate_repair', 'original_pr_repair']) {
test(`${kind} requires the admitted header-only native profile and bound candidate`, async t => {
  const root = mkdtempSync(join(tmpdir(), 'para-header-only-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const env = { ...environment(root), DEVFLEET_FORCE_OPENCODE: '1', PARA_PLATFORM_POOL: '1',
    PARA_PLATFORM_GATEWAY_URL: 'https://gateway.example.test/v1',
    PARA_PLATFORM_GATEWAY_KEYS_JSON: JSON.stringify({ coding: 'fixture-key' }) };
  const manifest = { commit_sha: 'c'.repeat(40), task_id: 'task-1' };
  mkdirSync(env.PARA_GITHUB_CANDIDATE_DIR);
  writeFileSync(join(env.PARA_GITHUB_CANDIDATE_DIR, 'manifest.json'), JSON.stringify(manifest));
  const repair = kind === 'original_pr_repair';
  const budgetKind = repair ? kind : 'github_opencode_workspace';
  const schema = repair ? 'strategic-pr-repair/v1' : 'strategic-workspace/v1';
  const source = repair ? 'b'.repeat(40) : env.GITHUB_SHA;
  const accepted = { ...identity, kind, publication_candidate: manifest,
    ...(repair ? { pull_request: 7, source_sha: source, controller_sha: env.GITHUB_SHA,
      publication_authorization: { schema: 'strategic-pr-publication/v1', authorized: true,
        usage_complete: true, request_id: identity.request_id, source_sha: source,
        controller_sha: env.GITHUB_SHA } } : {}),
    model_allocation: { status: 'admitted', model: 'coding', approved_models: ['coding'],
      provider: 'openai', execution_isolation: OPENCODE_CREDENTIAL_ISOLATION },
    strategic_budget: { kind: budgetKind, schema, request_id: identity.request_id,
      binding_id: 'd'.repeat(32), source_sha: source, controller_sha: env.GITHUB_SHA,
      model: 'coding', provider: 'openai' } };
  const fetchStatus = async (url, options) => ({ ok: true, json: async () => {
    if (url.endsWith('/claim')) return { ...JSON.parse(options.body), schema,
      kind: budgetKind, request_id: identity.request_id, binding_id: 'd'.repeat(32),
      deadline: new Date(Date.now()+60000).toISOString(), model: 'coding', device_id: 'cloud',
      bootstrap_token: 'fixture-bootstrap-token-at-least-32-characters',
      gateway_url: `https://xiu-ci.com/api/service/mac-control/strategic-runs/${identity.request_id}/v1` };
    if (url.endsWith('/close-grant')) return { accepted: true };
    return accepted;
  } });
  let verified = 0, launched = 0;
  const options = { env, fetchStatus,
    verifyFeedbackIsolation: () => { verified += 1; },
    spawnWorker: (_bin, _args, options) => {
      launched += 1;
      assert.equal(options.env.PARA_STRATEGIC_REQUEST_ID, identity.request_id);
      assert.equal(options.env.MODSTORE_PARA_DISPATCH_TOKEN, undefined);
      assert.equal(options.env.PARA_PLATFORM_GATEWAY_KEYS_JSON, undefined);
      const child = new EventEmitter(); child.kill = () => {}; return child;
    } };
  assert.equal(await runGithubExecutor(options), 0);
  assert.equal(verified, 1); assert.equal(launched, 1);
  assert.deepEqual(JSON.parse(readFileSync(join(env.PARA_GITHUB_EVIDENCE_DIR, 'execution.json'))), {
    request_id: identity.request_id, run_id: '123', status: 'awaiting_publication', finished: false,
    execution_isolation: OPENCODE_CREDENTIAL_ISOLATION, source_sha: source,
    ...(repair ? { controller_sha: env.GITHUB_SHA } : {}), candidate_sha: manifest.commit_sha,
  });
  await assert.rejects(runGithubExecutor({ ...options, verifyFeedbackIsolation: () => { throw new Error('native_boundary_missing'); } }), /native_boundary_missing/);
  assert.equal(launched, 1);
  const binding = accepted.strategic_budget;
  if (repair) {
    binding.request_id = '22222222-3333-5444-8555-666666666666';
    await assert.rejects(runGithubExecutor(options), /requires_original_isolated_budget_binding/);
    binding.request_id = identity.request_id;
    assert.equal(launched, 1);
  }
  delete accepted.strategic_budget;
  await assert.rejects(runGithubExecutor(options), repair ? /requires_non_exportable/ : /requires_original_isolated_budget_binding/);
  accepted.strategic_budget = binding;
  assert.equal(launched, 1);
  accepted.model_allocation.execution_isolation = 'srt-0.0.83-masked-platform-v1';
  await assert.rejects(runGithubExecutor(options), /requires_non_exportable/);
  assert.equal(launched, 1);
});
}

test('original PR task capability waits for the original submit acknowledgement and never impersonates an event', async () => {
  const request = identity.request_id, source = 'b'.repeat(40), attempt = 'c'.repeat(32);
  const marker = createHash('sha256').update(request).digest('hex').slice(0, 32);
  const env = { ...environment('/unused'), DEVFLEET_FORCE_OPENCODE: '1', PARA_PLATFORM_POOL: '1',
    PARA_STRATEGIC_REQUEST_ID: request, PARA_STRATEGIC_KIND: 'original_pr_repair',
    PARA_STRATEGIC_BOOTSTRAP_TOKEN: 'b'.repeat(48), PARA_STRATEGIC_DEVICE_ID: 'cloud',
    PARA_OPENCODE_MODEL: 'coding', PARA_PLATFORM_MODEL: 'coding',
    PARA_PLATFORM_GATEWAY_URL: `https://xiu-ci.com/api/service/mac-control/strategic-runs/${request}/v1` };
  const task = { task_id: 'para-1', subtask_id: 'sub-1', title: `[xcmax:${marker}:${attempt}] Repair PR #7`,
    description: 'original approved task', repo_url: 'https://github.com/owner/repo.git',
    base_branch: source, work_branch: 'devfleet/original', auto_merge: false };
  let calls = 0, sleeps = 0, overrides = {};
  const fetchControl = async (_url, options) => {
    if (++calls === 1) return { ok: false, status: 409,
      json: async () => ({ detail: 'workspace original task receipt is pending' }) };
    return { ok: true, json: async () => ({ ...JSON.parse(options.body), schema: 'strategic-pr-repair/v1',
      kind: 'original_pr_repair', request_id: request, grant_id: 'd'.repeat(32), role: 'fix',
      source_sha: source, model: 'coding', model_token: 'm'.repeat(48), deadline: new Date(Date.now()+60000).toISOString(),
      gateway_url: env.PARA_PLATFORM_GATEWAY_URL, ...overrides }) };
  };
  const grant = await bindWorkspaceTask(task, { env, fetchControl, sleep: async () => { sleeps += 1; } });
  assert.equal(calls, 2); assert.equal(sleeps, 1);
  assert.equal(Object.hasOwn(grant, 'event_id'), false);
  assert.equal(grant.source_sha, source);
  assert.equal(grant.modelEnv.MODSTORE_PARA_DISPATCH_TOKEN, undefined);
  assert.equal(grant.modelEnv.PARA_STRATEGIC_BOOTSTRAP_TOKEN, undefined);
  requireWorkspaceCandidate(task, grant, env);
  for (const change of [{ event_id: 1 }, { source_sha: env.GITHUB_SHA },
    { schema: 'strategic-workspace/v1' }, { attempt_id: 'e'.repeat(32) },
    { request_id: '22222222-3333-5444-8555-666666666666' }]) {
    overrides = change;
    await assert.rejects(bindWorkspaceTask(task, { env, fetchControl }), /task_grant_mismatch/);
  }
});

test('an original PR candidate with unknown usage cannot hand off, and cancellation stops the wait', async t => {
  const root = mkdtempSync(join(tmpdir(), 'para-original-hold-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const env = { ...environment(root), DEVFLEET_FORCE_OPENCODE: '1', PARA_PLATFORM_POOL: '1' };
  const manifest = { commit_sha: 'c'.repeat(40), task_id: 'para-1' };
  mkdirSync(env.PARA_GITHUB_CANDIDATE_DIR);
  writeFileSync(join(env.PARA_GITHUB_CANDIDATE_DIR, 'manifest.json'), JSON.stringify(manifest));
  const accepted = { ...identity, kind: 'original_pr_repair', pull_request: 7, source_sha: 'b'.repeat(40),
    publication_candidate: manifest, publication_authorization: { schema: 'strategic-pr-publication/v1',
      authorized: false, usage_complete: false },
    model_allocation: { status: 'admitted', model: 'coding', provider: 'openai',
      execution_isolation: OPENCODE_CREDENTIAL_ISOLATION },
    strategic_budget: { kind: 'original_pr_repair', schema: 'strategic-pr-repair/v1', request_id: identity.request_id,
      binding_id: 'd'.repeat(32), source_sha: 'b'.repeat(40), controller_sha: env.GITHUB_SHA, model: 'coding', provider: 'openai' } };
  let sleeps = 0, launches = 0;
  const result = await runGithubExecutor({ env, verifyFeedbackIsolation: () => {},
    fetchStatus: async (url, options) => ({ ok: true, json: async () => {
      if (url.endsWith('/claim')) return { ...JSON.parse(options.body), schema: 'strategic-pr-repair/v1',
        kind: 'original_pr_repair', request_id: identity.request_id, binding_id: 'd'.repeat(32),
        deadline: new Date(Date.now()+60000).toISOString(), model: 'coding', device_id: 'cloud',
        bootstrap_token: 'b'.repeat(48), gateway_url: `https://xiu-ci.com/api/service/mac-control/strategic-runs/${identity.request_id}/v1` };
      if (url.endsWith('/close-grant')) return { accepted: true };
      return accepted;
    } }),
    sleep: async () => { sleeps += 1; assert.equal(existsSync(join(env.PARA_GITHUB_EVIDENCE_DIR, 'execution.json')), false);
      accepted.finished = true; accepted.status = 'cancel_requested'; },
    spawnWorker: () => { launches += 1; const child = new EventEmitter(); child.kill = () => {}; return child; },
  });
  assert.equal(result, 1); assert.equal(launches, 1); assert.equal(sleeps, 1);
  assert.equal(existsSync(join(env.PARA_GITHUB_EVIDENCE_DIR, 'execution.json')), false);
});
function environment(root, stage = 'execute') {
  return { GITHUB_ACTIONS: 'true', GITHUB_RUN_ATTEMPT: '1', GITHUB_RUN_ID: '123', GITHUB_SHA: 'a'.repeat(40),
    GITHUB_REPOSITORY: 'owner/repo', PARA_GITHUB_STAGE: stage, PARA_GITHUB_REQUEST_ID: identity.request_id,
    PARA_GITHUB_CANDIDATE_DIR: join(root, 'candidate'), PARA_GITHUB_EVIDENCE_DIR: join(root, 'evidence'), MODSTORE_PARA_DISPATCH_TOKEN: 'management' };
}
for (const kind of ['original_pr_repair', 'customer_feedback_repair', 'training_candidate_repair']) {
test(`${kind} cannot launch a credential-bearing model, including login and OpenCode`, async () => {
  const root = mkdtempSync(join(tmpdir(), 'para-repair-credentials-'));
  try {
    mkdirSync(join(root, '.codex'));
    writeFileSync(join(root, '.codex', 'auth.json'), JSON.stringify({ access_token: 'fixture-login-only' }));
    const accepted = { ...identity, kind,
      ...(kind === 'original_pr_repair' ? { pull_request: 7, source_sha: 'b'.repeat(40) } : {}) };
    const reason = kind !== 'original_pr_repair'
      ? 'customer_feedback_requires_non_exportable_model_credentials'
      : 'original_pr_repair_requires_non_exportable_model_credentials';
    for (const credentials of [
      { CODEX_API_KEY: 'fixture-codex-only' },
      { OPENAI_API_KEY: 'fixture-openai-only' },
      { HOME: root, CODEX_HOME: join(root, '.codex') },
      { DEVFLEET_FORCE_OPENCODE: '1', OPENCODE_API_KEY: 'fixture-opencode-only' },
    ]) {
      await assert.rejects(runGithubExecutor({ env: { ...environment(root), ...credentials },
        fetchStatus: async () => ({ ok: true, json: async () => accepted }),
        spawnWorker: () => assert.fail('the untrusted repair must never receive a model process'),
      }), { message: reason });
      const evidence = readFileSync(join(root, 'evidence', 'execution.json'), 'utf8');
      assert.equal(JSON.parse(evidence).status, 'blocked');
      assert.equal(JSON.parse(evidence).reason, reason);
      assert.doesNotMatch(evidence, /fixture-(?:codex|openai|login|opencode)-only/);
    }
    if (kind !== 'original_pr_repair') {
      await assert.rejects(runGithubExecutor({ env: environment(root, 'resume'),
        fetchStatus: async () => ({ ok: true, json: async () => accepted }),
        spawnWorker: () => assert.fail('resuming a customer task cannot bypass the credential boundary'),
      }), /customer_feedback_requires_non_exportable_model_credentials/);
    }
    for (const stage of ['execute', 'resume']) {
      for (const conclusion of ['success', 'failure']) {
        assert.equal(await runGithubExecutor({ env: environment(root, stage),
          fetchStatus: async () => ({ ok: true, json: async () => ({ ...accepted, finished: true, conclusion }) }),
          spawnWorker: () => assert.fail('completed repair readback is read-only'),
        }), conclusion === 'success' ? 0 : 1);
      }
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});
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
      }), CODEX_API_KEY: 'fixture-agent-plan-key', DEVFLEET_CODEX_MODEL_CANDIDATES: 'ark-code-latest' };
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
    reads = 0;
    const agentPlan = { ...model_allocation, model: 'ark-code-latest', agent_plan_first: true,
      approved_models: ['ark-code-latest', 'coding-route'] };
    const withPlan = await runGithubExecutor({ env,
      fetchStatus: () => stub({ ...identity, finished: ++reads > 1, conclusion: 'success', model_allocation: agentPlan })(),
      spawnWorker: (_exe, _args, { env: child }) => {
        assert.equal(child.CODEX_API_KEY, 'fixture-agent-plan-key');
        assert.equal(child.PARA_PLATFORM_AGENT_PLAN_FIRST, '1');
        assert.deepEqual(JSON.parse(child.PARA_PLATFORM_APPROVED_KEYRING), {
          'ark-code-latest': 'fixture-agent-plan-key', 'coding-route': 'fixture-platform-key',
        });
        return agent;
      },
    });
    assert.equal(withPlan, 0);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('OpenCode binds the admitted model, gateway and only that model credential', async () => {
  const root = mkdtempSync(join(tmpdir(), 'para-opencode-'));
  try {
    const env = { ...environment(root, 'resume'), DEVFLEET_FORCE_OPENCODE: '1', PARA_PLATFORM_POOL: '1',
      PARA_PLATFORM_GATEWAY_URL: 'https://gateway.example.test/v1/',
      PARA_PLATFORM_GATEWAY_KEYS_JSON: JSON.stringify({ 'coding-route': 'fixture-admitted-key', 'backup-route': 'fixture-backup-key' }),
      PARA_OPENCODE_MODEL: 'unapproved-alias', OPENCODE_API_KEY: 'fixture-unapproved-key',
      CODEX_API_KEY: 'fixture-other-cli-key', OPENAI_API_KEY: 'fixture-other-provider-key' };
    const model_allocation = { status: 'admitted', model: 'coding-route', approved_models: ['coding-route', 'backup-route'] };
    let reads = 0, launches = 0;
    const result = await runGithubExecutor({ env,
      fetchStatus: async () => ({ ok: true, json: async () => ({ ...identity, model_allocation, finished: ++reads > 1, conclusion: 'success' }) }),
      spawnWorker: (_exe, _args, { env: child }) => {
        launches += 1;
        assert.equal(child.PARA_OPENCODE_MODEL, model_allocation.model);
        assert.equal(child.OPENCODE_API_KEY, 'fixture-admitted-key');
        for (const key of ['CODEX_API_KEY', 'OPENAI_API_KEY', 'PARA_PLATFORM_GATEWAY_KEY', 'PARA_PLATFORM_GATEWAY_KEYS_JSON', 'PARA_PLATFORM_APPROVED_KEYRING']) {
          assert.equal(child[key], undefined, key);
        }
        const config = openCodePlatformConfig(modelChildEnv(child, { tool: 'opencode' }));
        assert.equal(config.model, 'xcmax/coding-route');
        assert.equal(config.provider.xcmax.options.baseURL, 'https://gateway.example.test/v1');
        const agent = new EventEmitter(); agent.kill = () => {}; return agent;
      },
    });
    assert.equal(result, 0); assert.equal(launches, 1);
    const denied = (overrides, allocation = model_allocation) => runGithubExecutor({ env: { ...env, ...overrides },
      fetchStatus: async () => ({ ok: true, json: async () => ({ ...identity, model_allocation: allocation }) }),
      spawnWorker: () => assert.fail('an incompatible allocation must not start a model'),
    });
    await assert.rejects(denied({ PARA_PLATFORM_POOL: '0' }, undefined), /opencode_requires_platform_admission/);
    await assert.rejects(denied({}, { ...model_allocation, status: 'waiting' }), /platform_model_allocation/);
    await assert.rejects(denied({}, { ...model_allocation, approved_models: ['unapproved-alias'] }), /platform_model_allocation/);
    await assert.rejects(denied({ PARA_PLATFORM_GATEWAY_KEYS_JSON: '{}' }), /platform_model_allocation/);
    await assert.rejects(denied({ PARA_PLATFORM_GATEWAY_URL: 'http://gateway.example.test/v1' }), /OpenCode/);
    await assert.rejects(denied({}, { status: 'admitted', model: 'ark-code-latest', agent_plan_first: true,
      approved_models: ['ark-code-latest', 'coding-route'] }), /opencode_agent_plan_not_supported/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
