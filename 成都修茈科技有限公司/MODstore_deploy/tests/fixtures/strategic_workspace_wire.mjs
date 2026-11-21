// The real Actions controller and Para handleTask consume an owned local fixture.
// Only SRT launch is replaced on this unsupported host; no publication is performed.
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { readFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const { env, task } = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const tools = process.env.WORKSPACE_RUNTIME_TOOLS;
const loopback = process.env.WORKSPACE_LOOPBACK;
const nativeFetch = globalThis.fetch;
const forward = (url, options) => {
  const parsed = new URL(url);
  if (['https://xiu-ci.com', 'https://para.example.test'].includes(parsed.origin)) {
    return nativeFetch(loopback + parsed.pathname, options);
  }
  assert.equal(parsed.hostname, '127.0.0.1');
  return nativeFetch(url, options);
};
globalThis.fetch = forward;
const { runGithubExecutor } = await import(pathToFileURL(join(tools, 'github_para_executor.mjs')));
const { openCodePlatformConfig, runOpenCodeLive } = await import(pathToFileURL(join(tools, 'opencode_agent.mjs')));
let execution;
const runAgent = async (cwd, prompt, options) => {
  assert.equal(options.reportOnly, false);
  assert.equal(options.env.MODSTORE_PARA_DISPATCH_TOKEN, undefined);
  assert.equal(options.env.PARA_STRATEGIC_BOOTSTRAP_TOKEN, undefined);
  assert.notEqual(options.env.OPENCODE_API_KEY, 'workspace_task_binding_required');
  const config = openCodePlatformConfig(options.env);
  config.provider.xcmax.options.baseURL = loopback + new URL(config.provider.xcmax.options.baseURL).pathname;
  const cache = join(env.HOME, 'opencode');
  mkdirSync(cache, { recursive: true });
  const modelEnv = { ...options.env, OPENCODE_CONFIG_CONTENT: JSON.stringify(config),
    XDG_CONFIG_HOME: join(cache, 'config'), XDG_CACHE_HOME: join(cache, 'cache'),
    XDG_DATA_HOME: join(cache, 'data'), XDG_STATE_HOME: join(cache, 'state'),
    OPENCODE_DISABLE_PROJECT_CONFIG: 'true', OPENCODE_DISABLE_AUTOUPDATE: 'true', OPENCODE_DISABLE_MODELS_FETCH: 'true',
    OPENCODE_PERMISSION: JSON.stringify({ '*': 'deny', read: 'allow', write: 'allow', edit: 'allow', glob: 'allow', grep: 'allow', list: 'allow' }) };
  return runOpenCodeLive(env.DEVFLEET_OPENCODE_AGENT, cwd, prompt, modelEnv,
    { ...options, platform: config, timeoutMs: Math.min(options.timeoutMs, 45000) });
};
const code = await runGithubExecutor({ env, fetchStatus: forward,
  sleep: () => new Promise(resolve => setTimeout(resolve, 100)),
  verifyFeedbackIsolation: () => {}, // Existing native-host suite verifies SRT itself.
  spawnWorker: (_exe, _args, options) => {
    assert.equal(options.env.MODSTORE_PARA_DISPATCH_TOKEN, undefined);
    assert.equal(options.env.OPENCODE_API_KEY, 'workspace_task_binding_required');
    const child = new EventEmitter();
    child.kill = () => {};
    Object.assign(process.env, options.env);
    delete process.env.MODSTORE_PARA_DISPATCH_TOKEN;
    execution = (async () => {
      const { handleTask } = await import(pathToFileURL(join(tools, 'para_e2e_agent.mjs')));
      await handleTask({ readyState: 1, send() {} }, task, { runAgent });
    })();
    execution.catch(error => { process.stderr.write(error.stack + '\n'); child.emit('error', error); });
    return child;
  } });
await execution;
assert.equal(code, 0);
const result = JSON.parse(readFileSync(join(env.PARA_GITHUB_EVIDENCE_DIR, 'execution.json')));
assert.equal(result.finished, false);
assert.equal(result.status, 'awaiting_publication');
process.stdout.write('original approved engineering candidate completed\n');
