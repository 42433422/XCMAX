/** Bind existing Para tasks to their original work-order budget before OpenCode. */
import { createHash } from 'node:crypto';
import { modelChildEnv } from './credential_vault.mjs';
import { OPENCODE_CREDENTIAL_ISOLATION } from './opencode_agent.mjs';
import { controlServiceBase } from './strategic_report_controller.mjs';

const KIND = 'github_opencode_workspace';
const SCHEMA = 'strategic-workspace/v1';
const missing = 'workspace_task_binding_required';

async function post(url, token, body, fetchControl) {
  const response = await fetchControl(url, { method: 'POST', redirect: 'error',
    headers: { Authorization: `Bearer ${token}`, 'content-type': 'application/json' },
    body: JSON.stringify(body), signal: AbortSignal.timeout(20000) });
  if (!response.ok) {
    const error = new Error(`workspace_control_http_${response.status}`);
    // Only this ordinary creation race is retriable; it cannot issue a model call.
    if (response.status === 409 && (await response.json()).detail === 'workspace original task receipt is pending') {
      error.pendingOriginalReceipt = true;
    }
    throw error;
  }
  return response.json();
}

export async function beginWorkspacePhase({ env, accepted, fetchControl = fetch }) {
  const binding = accepted.strategic_budget;
  const repair = accepted.kind === 'original_pr_repair';
  const kind = repair ? 'original_pr_repair' : KIND;
  const schema = repair ? 'strategic-pr-repair/v1' : SCHEMA;
  const request = env.PARA_GITHUB_REQUEST_ID;
  const base = `${controlServiceBase(env)}/strategic-runs/${request}`;
  const identity = { run_id: Number(env.GITHUB_RUN_ID), run_attempt: 1,
    repository: env.GITHUB_REPOSITORY, source_sha: env.GITHUB_SHA,
    phase: env.PARA_GITHUB_STAGE, execution_isolation: OPENCODE_CREDENTIAL_ISOLATION };
  if (env.DEVFLEET_FORCE_OPENCODE !== '1' || env.PARA_PLATFORM_POOL !== '1'
      || binding?.kind !== kind || binding.request_id !== request
      || (repair ? binding.controller_sha : binding.source_sha) !== env.GITHUB_SHA
      || (repair && (binding.schema !== schema || binding.source_sha !== accepted.source_sha
        || env.PARA_GITHUB_STAGE !== 'execute'))
      || accepted.model_allocation?.execution_isolation !== OPENCODE_CREDENTIAL_ISOLATION
      || binding.model !== accepted.model_allocation?.model || binding.provider !== accepted.model_allocation?.provider) {
    throw new Error('workspace_requires_original_isolated_budget_binding');
  }
  const grant = await post(`${base}/claim`, env.MODSTORE_PARA_DISPATCH_TOKEN, identity, fetchControl);
  if (grant.schema !== schema || grant.kind !== kind || grant.request_id !== request
      || grant.binding_id !== binding.binding_id || grant.model !== binding.model
      || Object.keys(identity).some(key => grant[key] !== identity[key])
      || grant.gateway_url !== `${base}/v1` || !grant.device_id
      || typeof grant.bootstrap_token !== 'string' || grant.bootstrap_token.length < 32
      || !Number.isFinite(Date.parse(grant.deadline))) throw new Error('workspace_phase_grant_mismatch');
  const phaseEnv = { PARA_STRATEGIC_REQUEST_ID: request,
    PARA_STRATEGIC_KIND: kind,
    PARA_STRATEGIC_BOOTSTRAP_TOKEN: grant.bootstrap_token, PARA_STRATEGIC_DEVICE_ID: grant.device_id,
    PARA_STRATEGIC_BINDING_ID: binding.binding_id, PARA_STRATEGIC_DEADLINE: grant.deadline,
    PARA_PLATFORM_GATEWAY_URL: grant.gateway_url, PARA_PLATFORM_MODEL: grant.model,
    PARA_OPENCODE_MODEL: grant.model, OPENCODE_API_KEY: missing };
  return { env: phaseEnv, deadline: Date.parse(grant.deadline),
    close: () => post(`${base}/close-grant`, grant.bootstrap_token, { phase: identity.phase }, fetchControl) };
}

export async function bindWorkspaceTask(task, { env = process.env, fetchControl = fetch,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), now = Date.now } = {}) {
  const request = env.PARA_STRATEGIC_REQUEST_ID;
  if (!request) return null;
  const repair = env.PARA_STRATEGIC_KIND === 'original_pr_repair';
  const schema = repair ? 'strategic-pr-repair/v1' : SCHEMA;
  const marker = createHash('sha256').update(request).digest('hex').slice(0, 32);
  const match = String(task.title || '').match(/^\[xcmax:([0-9a-f]{32}):([0-9a-f]{32})\]/);
  if (env.GITHUB_ACTIONS !== 'true' || env.DEVFLEET_FORCE_OPENCODE !== '1'
      || request !== env.PARA_GITHUB_REQUEST_ID || env.GITHUB_RUN_ATTEMPT !== '1'
      || !match || match[1] !== marker || task.auto_merge === true
      || !env.PARA_STRATEGIC_BOOTSTRAP_TOKEN) throw new Error(missing);
  const base = `${controlServiceBase(env)}/strategic-runs/${request}`;
  const identity = { phase: env.PARA_GITHUB_STAGE, run_id: Number(env.GITHUB_RUN_ID),
    task_id: task.task_id, subtask_id: task.subtask_id, attempt_id: match[2],
    device_id: env.PARA_STRATEGIC_DEVICE_ID, title: task.title, description: task.description,
    repo_url: task.repo_url, base_branch: task.base_branch, work_branch: task.work_branch,
    auto_merge: false };
  let grant;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      grant = await post(`${base}/task-grant`, env.PARA_STRATEGIC_BOOTSTRAP_TOKEN, identity, fetchControl);
      break;
    } catch (error) {
      if (!error.pendingOriginalReceipt || attempt === 29) throw error;
      await sleep(1000);
    }
  }
  if (grant.schema !== schema || grant.request_id !== request
      || ['phase', 'run_id', 'task_id', 'subtask_id', 'attempt_id', 'device_id'].some(key => grant[key] !== identity[key])
      || (repair ? (grant.kind !== 'original_pr_repair' || Object.hasOwn(grant, 'event_id')
        || grant.source_sha !== task.base_branch) : (!Number.isSafeInteger(grant.event_id) || grant.event_id < 1))
      || !/^[0-9a-f]{32}$/.test(grant.grant_id) || grant.gateway_url !== `${base}/v1`
      || grant.model !== env.PARA_OPENCODE_MODEL || typeof grant.model_token !== 'string'
      || grant.model_token.length < 32) throw new Error('workspace_task_grant_mismatch');
  const timeoutMs = Date.parse(grant.deadline) - now();
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error('workspace_phase_deadline_expired');
  return { ...grant, timeoutMs,
    modelEnv: modelChildEnv({ ...env, OPENCODE_API_KEY: grant.model_token }, { tool: 'opencode' }),
    close: () => post(`${base}/close-grant`, env.PARA_STRATEGIC_BOOTSTRAP_TOKEN,
      { phase: identity.phase, grant_id: grant.grant_id }, fetchControl) };
}

export function requireWorkspaceCandidate(task, grant, env = process.env) {
  if (!env.PARA_STRATEGIC_REQUEST_ID) return;
  if (!grant || grant.role !== 'fix' || grant.phase !== 'execute'
      || grant.task_id !== task.task_id || grant.subtask_id !== task.subtask_id) {
    throw new Error('workspace_candidate_requires_original_task_grant');
  }
}
