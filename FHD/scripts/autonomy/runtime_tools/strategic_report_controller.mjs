/** Trusted control path for an approved read-only business report. */
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runOpenCodeAgent } from './opencode_agent.mjs';

const KIND = 'github_opencode_report';
const SCHEMA = 'strategic-remote-report/v1';
export function controlServiceBase(env) {
  const base = new URL(env.MODSTORE_PUBLIC_ORIGIN || env.PUBLIC_ORIGIN || 'https://xiu-ci.com');
  if (base.protocol !== 'https:' || base.username || base.password || base.pathname !== '/'
      || base.search || base.hash) throw new Error('invalid_modstore_public_origin');
  return base.origin + '/api/service/mac-control';
}

export async function runStrategicReport({ env, accepted, state, fetchControl = fetch,
  runAgent = runOpenCodeAgent, now = Date.now, sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
}) {
  const request = env.PARA_GITHUB_REQUEST_ID;
  const base = controlServiceBase(env) + '/strategic-runs';
  const identity = { run_id: Number(env.GITHUB_RUN_ID), run_attempt: 1,
    repository: env.GITHUB_REPOSITORY, source_sha: env.GITHUB_SHA };
  if (env.PARA_GITHUB_STAGE !== 'execute' || env.DEVFLEET_FORCE_OPENCODE !== '1'
      || accepted.kind !== KIND || accepted.source_sha !== identity.source_sha) {
    throw new Error('strategic_report_requires_approved_opencode_controller');
  }
  if (env.GITHUB_OUTPUT) appendFileSync(env.GITHUB_OUTPUT, 'strategic_report=true\n');
  const directory = env.PARA_GITHUB_EVIDENCE_DIR;
  mkdirSync(directory, { recursive: true });
  const control = async (route, body) => {
    const response = await fetchControl(`${base}/${request}/${route}`, {
      method: 'POST', headers: { Authorization: `Bearer ${env.MODSTORE_PARA_DISPATCH_TOKEN}`,
        'content-type': 'application/json' }, body: JSON.stringify(body), redirect: 'error',
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error(`strategic_control_http_${response.status}`);
    return response.json();
  };
  for (let attempt = 0; !accepted.ready && attempt < 18; attempt += 1) {
    if (accepted.finished || !['dispatching', 'requested', 'unknown'].includes(accepted.status)) {
      throw new Error('strategic_report_request_already_claimed');
    }
    await sleep(1000);
    accepted = await state();
  }
  if (!accepted.ready) throw new Error('strategic_report_not_ready');
  const grant = await control('claim', identity);
  if (grant.schema !== SCHEMA || grant.kind !== KIND || grant.request_id !== request
      || Object.keys(identity).some(key => grant[key] !== identity[key])
      || typeof grant.binding_id !== 'string' || !/^[0-9a-f]{32}$/.test(grant.binding_id)
      || !Number.isSafeInteger(grant.owner_user_id) || grant.owner_user_id < 1
      || grant.gateway_url !== `${base}/${request}/v1` || typeof grant.model_token !== 'string'
      || grant.model_token.length < 32 || !/^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$/.test(grant.model)
      || typeof grant.task !== 'string' || !grant.task.trim()) throw new Error('strategic_report_grant_mismatch');
  const workspace = await mkdtemp(join(tmpdir(), 'para-strategic-report-'));
  const receipt = { schema: SCHEMA, kind: KIND, request_id: request, binding_id: grant.binding_id,
    owner_user_id: grant.owner_user_id, ...identity };
  let failed;
  try {
    const timeoutMs = Date.parse(grant.deadline) - now();
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1) throw new Error('strategic_report_deadline_expired');
    const prompt = `Produce the approved read-only business report. Use only the supplied task context.\nTask: ${grant.task}\nContext:\n${JSON.stringify(grant.input_data, null, 2)}`;
    writeFileSync(join(workspace, 'TASK.md'), prompt + '\n', { mode: 0o600 });
    // Only the task-scoped model grant enters the existing trusted SRT controller.
    // AgentEnvironment subsequently exposes a placeholder to the model workload.
    const modelEnv = { PATH: env.PATH, DEVFLEET_OPENCODE_AGENT: env.DEVFLEET_OPENCODE_AGENT,
      DEVFLEET_OPENCODE_SANDBOX_ENTRY: env.DEVFLEET_OPENCODE_SANDBOX_ENTRY,
      PARA_PLATFORM_POOL: '1', PARA_PLATFORM_MODEL: grant.model, PARA_OPENCODE_MODEL: grant.model,
      PARA_PLATFORM_GATEWAY_URL: grant.gateway_url, OPENCODE_API_KEY: grant.model_token };
    const report = await runAgent(workspace, prompt, { env: modelEnv, timeoutMs, reportOnly: true,
      log: () => {} });
    if (typeof report !== 'string' || !report.trim() || Buffer.byteLength(report) > 500000) {
      throw new Error('strategic_report_output_invalid');
    }
    writeFileSync(join(directory, 'report.md'), report, { mode: 0o600 });
    Object.assign(receipt, { status: 'completed', report_sha256: createHash('sha256').update(report).digest('hex') });
  } catch (error) {
    failed = error;
    Object.assign(receipt, { status: 'failed', error: 'strategic_report_execution_failed' });
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
  writeFileSync(join(directory, 'execution.json'), JSON.stringify(receipt) + '\n', { mode: 0o600 });
  await control('result', receipt);
  if (failed) throw failed;
  return 0; // Portfolio completion awaits the native job and immutable artifact readback.
}
