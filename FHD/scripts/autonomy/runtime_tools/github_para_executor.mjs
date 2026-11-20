/** Bounded stages around the existing Para device. This process cannot publish. */
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export async function runGithubExecutor({ env = process.env, fetchStatus = fetch, spawnWorker = spawn,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), now = Date.now } = {}) {
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
    const response = await fetchStatus(`https://xiu-ci.com/api/service/mac-control/github-runs/${request}`, {
      headers: { Authorization: `Bearer ${env.MODSTORE_PARA_DISPATCH_TOKEN}` }, redirect: 'error',
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error(`management_readback_http_${response.status}`);
    const value = await response.json();
    if (value.request_id !== request || (value.run_id && String(value.run_id) !== run)
        || value.repository !== env.GITHUB_REPOSITORY || !Number.isSafeInteger(value.issue_number)
        || value.issue_number < 1 || (value.benchmark_protocol
          && value.benchmark_protocol.source_sha !== env.GITHUB_SHA)) throw new Error('management_dispatch_mismatch');
    return value;
  }
  const accepted = await state();
  if (accepted.finished) {
    if (stage !== 'resume') throw new Error('management_dispatch_already_finished');
    mkdirSync(directory, { recursive: true });
    writeFileSync(join(directory, 'execution.json'), JSON.stringify(accepted) + '\n');
    return accepted.conclusion === 'success' ? 0 : 1;
  }
  const agentEnv = { ...env, PARA_GITHUB_ISSUE_NUMBER: String(accepted.issue_number) };
  delete agentEnv.MODSTORE_PARA_DISPATCH_TOKEN;
  delete agentEnv.PARA_CODEX_AUTH_JSON;
  delete agentEnv.PARA_CODEX_CONFIG_TOML;
  const allocation = accepted.model_allocation;
  if (env.PARA_PLATFORM_POOL === '1' || allocation) {
    if (env.PARA_PLATFORM_POOL !== '1' || allocation?.status !== 'admitted'
        || !/^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$/.test(allocation.model || '')
        || !env.PARA_PLATFORM_GATEWAY_KEY?.trim()) {
      throw new Error('platform_model_allocation_or_gateway_missing');
    }
    agentEnv.CODEX_API_KEY = env.PARA_PLATFORM_GATEWAY_KEY;
    delete agentEnv.OPENAI_API_KEY;
    delete agentEnv.DEVFLEET_CODEX_API_KEY_ENV;
    agentEnv.PARA_PLATFORM_MODEL = allocation.model;
  }
  delete agentEnv.PARA_PLATFORM_GATEWAY_KEY;
  const agent = spawnWorker(process.execPath, [join(dirname(fileURLToPath(import.meta.url)), 'para_e2e_agent.mjs')], {
    env: agentEnv, stdio: ['ignore', 'inherit', 'inherit'],
  });
  let ended = false;
  agent.once('exit', () => { ended = true; });
  agent.once('error', () => { ended = true; });
  const stop = () => { if (!ended) agent.kill('SIGTERM'); };
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
  mkdirSync(directory, { recursive: true });
  try {
    const deadline = now() + 100 * 60 * 1000;
    while (now() < deadline) {
      if (ended) throw new Error('Para exited before its original receipt was acknowledged');
      const current = await state();
      const path = join(env.PARA_GITHUB_CANDIDATE_DIR || directory, 'manifest.json');
      if (stage === 'execute' && existsSync(path) && current.publication_candidate) {
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
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runGithubExecutor().then(code => { process.exitCode = code; }).catch(error => {
    console.error(error.message); process.exitCode = 1;
  });
}
