/** Bounded stages around the existing Para device. This process cannot publish. */
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { ARK_AGENT_PLAN_MODEL } from './codex_model_gateway.mjs';
import { assertOpenCodeHost, openCodeSandboxEntry, openCodePlatformConfig,
  OPENCODE_CREDENTIAL_ISOLATION } from './opencode_agent.mjs';
import { controlServiceBase, runStrategicReport } from './strategic_report_controller.mjs';
import { beginWorkspacePhase } from './strategic_workspace_controller.mjs';

function assertFeedbackIsolation(env) {
  assertOpenCodeHost();
  if (process.platform !== 'linux' || !openCodeSandboxEntry(env)) {
    throw new Error('customer_feedback_requires_non_exportable_model_credentials');
  }
}

export async function runGithubExecutor({ env = process.env, fetchStatus = fetch, spawnWorker = spawn,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), now = Date.now,
  verifyFeedbackIsolation = assertFeedbackIsolation, runReport = runStrategicReport } = {}) {
  const request = env.PARA_GITHUB_REQUEST_ID || '', run = env.GITHUB_RUN_ID || '';
  const stage = env.PARA_GITHUB_STAGE, directory = env.PARA_GITHUB_EVIDENCE_DIR;
  if (['GH_TOKEN', 'CI_COMMIT_TOKEN', 'GITHUB_PERSONAL_ACCESS_TOKEN'].some(key => env[key])) {
    throw new Error('executor_must_not_receive_publication_credentials');
  }
  if (env.GITHUB_ACTIONS !== 'true' || env.GITHUB_RUN_ATTEMPT !== '1'
      || !['execute', 'resume'].includes(stage) || !/^[0-9a-f-]{36}$/.test(request)
      || !/^\d+$/.test(run) || !/^[0-9a-f]{40}$/.test(env.GITHUB_SHA || '')
      || !directory || !env.MODSTORE_PARA_DISPATCH_TOKEN) throw new Error('invalid_executor_identity');
  async function state() {
    const response = await fetchStatus(`${controlServiceBase(env)}/github-runs/${request}`, {
      headers: { Authorization: `Bearer ${env.MODSTORE_PARA_DISPATCH_TOKEN}` }, redirect: 'error',
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error(`management_readback_http_${response.status}`);
    const value = await response.json();
    if (value.request_id !== request || (value.run_id && String(value.run_id) !== run)
        || value.repository !== env.GITHUB_REPOSITORY || (value.kind !== 'github_opencode_report'
          && (!Number.isSafeInteger(value.issue_number) || value.issue_number < 1)) || (value.benchmark_protocol
          && value.benchmark_protocol.source_sha !== env.GITHUB_SHA)) throw new Error('management_dispatch_mismatch');
    return value;
  }
  let accepted = await state();
  if (accepted.kind === 'github_opencode_report') {
    verifyFeedbackIsolation(env);
    return runReport({ env, accepted, state, fetchControl: fetchStatus, now, sleep });
  }
  const repair = accepted.kind === 'original_pr_repair';
  const customerRepair = ['customer_feedback_repair', 'training_candidate_repair'].includes(accepted.kind);
  if (repair) {
    for (let attempt = 0; !accepted.finished && !accepted.run_id && attempt < 18; attempt += 1) {
      await sleep(10000);
      accepted = await state();
    }
    if (accepted.kind !== 'original_pr_repair' || String(accepted.run_id) !== run
        || !/^[0-9a-f]{40}$/.test(accepted.source_sha || '')
        || !Number.isSafeInteger(accepted.pull_request) || accepted.pull_request < 1
        || (!accepted.finished && stage !== 'execute')) throw new Error('original_pr_dispatch_mismatch');
  }
  if (accepted.finished) {
    if (stage !== 'resume' && !repair && !customerRepair) throw new Error('management_dispatch_already_finished');
    mkdirSync(directory, { recursive: true });
    writeFileSync(join(directory, 'execution.json'), JSON.stringify(accepted) + '\n');
    return accepted.conclusion === 'success' ? 0 : 1;
  }
  const budgeted = accepted.strategic_budget?.kind === (repair ? 'original_pr_repair' : 'github_opencode_workspace');
  const isolatedFeedback = (customerRepair || repair) && env.DEVFLEET_FORCE_OPENCODE === '1'
    && env.PARA_PLATFORM_POOL === '1'
    && accepted.model_allocation?.execution_isolation === OPENCODE_CREDENTIAL_ISOLATION;
  if ((repair && (!budgeted || !isolatedFeedback)) || (customerRepair && !isolatedFeedback)) {
    // Raw keys and login material remain forbidden. Customer repair requires the
    // admitted native SRT mask profile and its original approved company task.
    const reason = customerRepair ? 'customer_feedback_requires_non_exportable_model_credentials'
      : 'original_pr_repair_requires_non_exportable_model_credentials';
    mkdirSync(directory, { recursive: true });
    writeFileSync(join(directory, 'execution.json'), JSON.stringify({
      request_id: request, run_id: run, finished: true, conclusion: 'failure', status: 'blocked', reason,
    }) + '\n');
    throw new Error(reason);
  }
  if (customerRepair && !budgeted) throw new Error('workspace_requires_original_isolated_budget_binding');
  let phase;
  if (budgeted) {
    verifyFeedbackIsolation(env);
    phase = await beginWorkspacePhase({ env, accepted, fetchControl: fetchStatus });
  }
  const agentEnv = { ...env, PARA_GITHUB_ISSUE_NUMBER: String(accepted.issue_number) };
  delete agentEnv.PARA_GITHUB_SOURCE_SHA;
  delete agentEnv.MODSTORE_PARA_DISPATCH_TOKEN;
  delete agentEnv.PARA_CODEX_AUTH_JSON;
  delete agentEnv.PARA_CODEX_CONFIG_TOML;
  const allocation = accepted.model_allocation;
  delete agentEnv.PARA_PLATFORM_MODEL;
  delete agentEnv.PARA_PLATFORM_MODEL_CANDIDATES;
  delete agentEnv.PARA_PLATFORM_APPROVED_KEYRING;
  delete agentEnv.PARA_PLATFORM_GATEWAY_KEYS_JSON;
  delete agentEnv.PARA_PLATFORM_AGENT_PLAN_FIRST;
  const openCode = env.DEVFLEET_FORCE_OPENCODE === '1';
  if (openCode && env.PARA_PLATFORM_POOL !== '1') throw new Error('opencode_requires_platform_admission');
  delete agentEnv.OPENCODE_API_KEY;
  delete agentEnv.PARA_OPENCODE_MODEL;
  if (phase) {
    Object.assign(agentEnv, phase.env);
    for (const key of ['CODEX_API_KEY', 'OPENAI_API_KEY', 'DEVFLEET_CODEX_API_KEY_ENV']) delete agentEnv[key];
  } else if (env.PARA_PLATFORM_POOL === '1' || allocation) {
    const approved = allocation?.approved_models ?? [allocation?.model];
    if (env.PARA_PLATFORM_POOL !== '1' || allocation?.status !== 'admitted'
        || !Array.isArray(approved) || !approved.length || approved[0] !== allocation.model
        || approved.some(model => typeof model !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$/.test(model))
        || new Set(approved).size !== approved.length) {
      throw new Error('platform_model_allocation_or_gateway_missing');
    }
    if (openCode && (allocation.agent_plan_first === true || allocation.model === ARK_AGENT_PLAN_MODEL
        || allocation.provider === 'ark_agent_plan')) throw new Error('opencode_agent_plan_not_supported');
    let keys;
    try {
      keys = env.PARA_PLATFORM_GATEWAY_KEYS_JSON?.trim()
        ? JSON.parse(env.PARA_PLATFORM_GATEWAY_KEYS_JSON)
        : Object.fromEntries(approved.map(model => [model, env.PARA_PLATFORM_GATEWAY_KEY]));
    } catch {
      throw new Error('invalid_platform_model_keyring');
    }
    if (!keys || typeof keys !== 'object' || Array.isArray(keys)) {
      throw new Error('invalid_platform_model_keyring');
    }
    if (allocation.agent_plan_first === true) {
      if (allocation.model !== ARK_AGENT_PLAN_MODEL || env.DEVFLEET_CODEX_MODEL_CANDIDATES !== ARK_AGENT_PLAN_MODEL) {
        throw new Error('agent_plan_primary_not_configured');
      }
      keys[ARK_AGENT_PLAN_MODEL] = env.CODEX_API_KEY;
      agentEnv.PARA_PLATFORM_AGENT_PLAN_FIRST = '1';
    }
    if (approved.some(model => !Object.hasOwn(keys, model)
          || typeof keys[model] !== 'string' || !/^\S+$/.test(keys[model]))) {
      throw new Error('platform_model_allocation_or_gateway_missing');
    }
    agentEnv.CODEX_API_KEY = keys[allocation.model];
    agentEnv.PARA_PLATFORM_APPROVED_KEYRING = JSON.stringify(
      Object.fromEntries(approved.map(model => [model, keys[model]])),
    );
    delete agentEnv.OPENAI_API_KEY;
    delete agentEnv.DEVFLEET_CODEX_API_KEY_ENV;
    agentEnv.PARA_PLATFORM_MODEL = allocation.model;
    agentEnv.PARA_PLATFORM_MODEL_CANDIDATES = approved.join(',');
    if (openCode) {
      agentEnv.PARA_OPENCODE_MODEL = allocation.model;
      agentEnv.OPENCODE_API_KEY = keys[allocation.model];
      const config = openCodePlatformConfig(agentEnv);
      if (isolatedFeedback) verifyFeedbackIsolation(agentEnv);
      agentEnv.PARA_PLATFORM_GATEWAY_URL = config.provider.xcmax.options.baseURL;
      delete agentEnv.CODEX_API_KEY;
      delete agentEnv.PARA_PLATFORM_APPROVED_KEYRING;
    }
  }
  delete agentEnv.PARA_PLATFORM_GATEWAY_KEY;
  let agent;
  try {
    agent = spawnWorker(process.execPath, [join(dirname(fileURLToPath(import.meta.url)), 'para_e2e_agent.mjs')], {
      env: agentEnv, stdio: ['ignore', 'inherit', 'inherit'],
    });
  } catch (error) {
    if (phase) await phase.close();
    throw error;
  }
  let ended = false;
  agent.once('exit', () => { ended = true; });
  agent.once('error', () => { ended = true; });
  const stop = () => { if (!ended) agent.kill('SIGTERM'); };
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
  mkdirSync(directory, { recursive: true });
  try {
    const deadline = Math.min(now() + 100 * 60 * 1000, phase?.deadline ?? Infinity);
    while (now() < deadline) {
      if (ended) throw new Error('Para exited before its original receipt was acknowledged');
      const current = await state();
      if (repair && (current.kind !== accepted.kind || current.source_sha !== accepted.source_sha
          || current.pull_request !== accepted.pull_request || String(current.run_id) !== run)) {
        throw new Error('original_pr_dispatch_changed');
      }
      const path = join(env.PARA_GITHUB_CANDIDATE_DIR || directory, 'manifest.json');
      if (stage === 'execute' && existsSync(path) && current.publication_candidate) {
        if (repair && !(current.publication_authorization?.schema === 'strategic-pr-publication/v1'
            && current.publication_authorization.authorized === true
            && current.publication_authorization.usage_complete === true
            && current.publication_authorization.request_id === request
            && current.publication_authorization.source_sha === accepted.source_sha
            && current.publication_authorization.controller_sha === env.GITHUB_SHA)) {
          if (current.finished) return 1;
          await sleep(10000);
          continue;
        }
        const manifest = JSON.parse(readFileSync(path, 'utf8'));
        if (JSON.stringify(manifest) !== JSON.stringify(current.publication_candidate)) {
          // Compare fields, not producer-controlled key order.
          const keys = Object.keys(manifest).sort();
          if (keys.join() !== Object.keys(current.publication_candidate).sort().join()
              || keys.some(key => manifest[key] !== current.publication_candidate[key])) {
            throw new Error('candidate_management_receipt_mismatch');
          }
        }
        writeFileSync(join(directory, 'execution.json'), JSON.stringify({ request_id: request,
          run_id: run, status: 'awaiting_publication', finished: false,
          ...((isolatedFeedback || phase) ? { execution_isolation: OPENCODE_CREDENTIAL_ISOLATION,
            source_sha: repair ? accepted.source_sha : env.GITHUB_SHA,
            ...(repair ? { controller_sha: env.GITHUB_SHA } : {}) } : {}),
          candidate_sha: manifest.commit_sha }) + '\n');
        return 0; // This stage is done; neither the team nor delivery is complete.
      }
      writeFileSync(join(directory, 'execution.json'), JSON.stringify({ ...current,
        executor: 'Para', machine: 'github-hosted', source_sha: env.GITHUB_SHA }) + '\n');
      if (current.finished) return stage === 'resume' && current.conclusion === 'success' ? 0 : 1;
      await sleep(10000);
    }
    throw new Error('management_receipt_deadline');
  } finally {
    stop(); process.off('SIGTERM', stop); process.off('SIGINT', stop);
    if (phase) await phase.close();
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runGithubExecutor().then(code => { process.exitCode = code; }).catch(error => {
    console.error(error.message); process.exitCode = 1;
  });
}
