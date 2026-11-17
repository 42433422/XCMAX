/** A bounded GitHub job around the existing Para agent; no model or repair implementation. */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export async function runGithubWorker({ env = process.env, fetchStatus = fetch, spawnWorker = spawn,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), now = Date.now } = {}) {
  const requestId = env.PARA_GITHUB_REQUEST_ID || '';
  const runId = env.GITHUB_RUN_ID || '';
  const serviceBase = env.MODSTORE_DISPATCH_BASE || 'https://xiu-ci.com';
  const serviceToken = env.MODSTORE_PARA_DISPATCH_TOKEN;
  const evidenceDir = env.PARA_GITHUB_EVIDENCE_DIR;
  const url = new URL(serviceBase);
  if (env.GITHUB_ACTIONS !== 'true' || env.GITHUB_RUN_ATTEMPT !== '1'
      || !/^[0-9a-f-]{36}$/.test(requestId) || !/^\d+$/.test(runId)
      || url.protocol !== 'https:' || url.username || url.password || !serviceToken || !evidenceDir) {
    throw new Error('GitHub worker identity or service configuration is invalid; no task started');
  }
  const endpoint = `${url.origin}/api/service/mac-control/github-runs/${requestId}`;
  async function state() {
    const response = await fetchStatus(endpoint, {
      headers: { Authorization: `Bearer ${serviceToken}` }, redirect: 'error',
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error(`management_readback_http_${response.status}`);
    const result = await response.json();
    if (result.request_id !== requestId || (result.run_id && String(result.run_id) !== runId)) {
      throw new Error('management_run_identity_mismatch');
    }
    return result;
  }
  const accepted = await state();
  if (accepted.repository !== env.GITHUB_REPOSITORY || !Number.isSafeInteger(accepted.issue_number)
      || accepted.issue_number < 1) throw new Error('management_issue_identity_mismatch');
  if (accepted.benchmark_protocol && (accepted.benchmark_protocol.source_sha !== env.GITHUB_SHA
      || accepted.benchmark_protocol.request_id !== requestId
      || accepted.benchmark_protocol.repository !== env.GITHUB_REPOSITORY)) {
    throw new Error('retort_frozen_source_mismatch');
  }
  if (accepted.finished) throw new Error('management_dispatch_already_finished');
  const agentEnv = { ...env };
  agentEnv.PARA_GITHUB_ISSUE_NUMBER = String(accepted.issue_number);
  delete agentEnv.MODSTORE_PARA_DISPATCH_TOKEN;
  delete agentEnv.PARA_CODEX_AUTH_JSON;
  delete agentEnv.PARA_CODEX_CONFIG_TOML;
  const agent = spawnWorker(process.execPath, [join(dirname(fileURLToPath(import.meta.url)), 'para_e2e_agent.mjs')], {
    env: agentEnv, stdio: ['ignore', 'inherit', 'inherit'],
  });
  let agentEnded = false;
  agent.once('exit', () => { agentEnded = true; });
  agent.once('error', () => { agentEnded = true; });
  const stop = () => { if (!agentEnded) agent.kill('SIGTERM'); };
  const terminate = () => { stop(); process.exit(143); };
  const interrupt = () => { stop(); process.exit(130); };
  process.once('SIGTERM', terminate);
  process.once('SIGINT', interrupt);
  mkdirSync(evidenceDir, { recursive: true });
  let last = { request_id: requestId, run_id: runId, finished: false, conclusion: 'unknown' };
  try {
    const deadline = now() + 100 * 60 * 1000;
    while (now() < deadline) {
      if (agentEnded) throw new Error('Para worker exited before management acknowledged completion');
      last = await state();
      writeFileSync(join(evidenceDir, 'execution.json'), JSON.stringify({
        ...last, executor: 'Para', machine: 'github-hosted', source_sha: env.GITHUB_SHA,
      }, null, 2) + '\n');
      if (last.finished) {
        return last.conclusion === 'success' ? 0 : 1;
      }
      await sleep(10000);
    }
    if (!last.finished) throw new Error('Management completion not confirmed before worker deadline');
  } finally {
    stop();
    process.off('SIGTERM', terminate);
    process.off('SIGINT', interrupt);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runGithubWorker().then(code => { process.exitCode = code; }).catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
