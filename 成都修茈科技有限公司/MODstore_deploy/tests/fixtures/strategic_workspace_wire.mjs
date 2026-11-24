// The real Actions controller and Para handleTask consume an owned local fixture.
// Only SRT launch is replaced on this unsupported host; no publication is performed.
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { readFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { mock } from 'node:test';
import { pathToFileURL } from 'node:url';
const { env, task, deadlineMode } = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const tools = process.env.WORKSPACE_RUNTIME_TOOLS;
const loopback = process.env.WORKSPACE_LOOPBACK;
const nativeFetch = globalThis.fetch;
const taskCloses = [];
let boundGrant;
const forward = async (url, options) => {
  const parsed = new URL(url);
  const controlled = ['https://xiu-ci.com', 'https://para.example.test'].includes(parsed.origin);
  if (!controlled) assert.equal(parsed.hostname, '127.0.0.1');
  const response = await nativeFetch(controlled ? loopback + parsed.pathname : url, options);
  if (deadlineMode && response.ok) {
    if (parsed.pathname.endsWith('/task-grant')) boundGrant = await response.clone().json();
    if (parsed.pathname.endsWith('/close-grant') && JSON.parse(options.body).grant_id) {
      taskCloses.push(JSON.parse(options.body));
    }
  }
  return response;
};
globalThis.fetch = forward;
const openCodeUrl = pathToFileURL(join(tools, 'opencode_agent.mjs'));
const openCode = await import(openCodeUrl);
if (deadlineMode) mock.module(openCodeUrl, { namedExports: { ...openCode, isOpenCodeReady: () => true } });
const { runGithubExecutor } = await import(pathToFileURL(join(tools, 'github_para_executor.mjs')));
const { openCodeExecutable, openCodePlatformConfig, runOpenCodeLive } = openCode;
// Match the injected Live SDK executor, not the native SRT launcher. The SDK,
// approved gateway configuration, file edit, SQL settlement and Git bundle are
// real; host/SRT admission remains covered by the separate native-host suite.
const isAvailable = tool => tool === 'opencode'
  && Boolean(openCodeExecutable(process.env)) && Boolean(openCodePlatformConfig(process.env));
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
if (deadlineMode) {
  const { beginWorkspacePhase } = await import(pathToFileURL(join(tools, 'strategic_workspace_controller.mjs')));
  const { controlServiceBase } = await import(pathToFileURL(join(tools, 'strategic_report_controller.mjs')));
  const accepted = await forward(`${controlServiceBase(env)}/github-runs/${env.PARA_GITHUB_REQUEST_ID}`, {
    headers: { Authorization: `Bearer ${env.MODSTORE_PARA_DISPATCH_TOKEN}` },
  }).then(response => response.json());
  const phase = await beginWorkspacePhase({ env, accepted, fetchControl: forward });
  Object.assign(process.env, env, phase.env);
  delete process.env.MODSTORE_PARA_DISPATCH_TOKEN;
  const nativeNow = Date.now;
  const timeouts = [];
  let prepared = false;
  const { handleTask } = await import(pathToFileURL(join(tools, 'para_e2e_agent.mjs')));
  try {
    await handleTask({ readyState: 1, send(raw) {
      const event = JSON.parse(raw);
      if (event.type === 'task_progress' && event.progress === 40) {
        prepared = true;
        Date.now = () => phase.deadline - (deadlineMode === 'expired' ? 0 : 15000);
      }
    } }, task, { runAgent: async (_cwd, _prompt, options) => {
      timeouts.push(options.timeoutMs);
      assert.equal(options.env.MODSTORE_PARA_DISPATCH_TOKEN, undefined);
      assert.equal(options.env.PARA_STRATEGIC_BOOTSTRAP_TOKEN, undefined);
      assert.equal(options.env.OPENCODE_API_KEY, boundGrant.model_token);
      throw Object.assign(new Error('fixture_executor_stopped'), { stderr: 'fixture_executor_stopped' });
    } });
    assert.deepEqual(taskCloses, [{ phase: 'execute', grant_id: boundGrant.grant_id }]);
  } finally {
    Date.now = nativeNow;
    await phase.close();
  }
  assert.equal(prepared, true);
  assert.deepEqual(timeouts, deadlineMode === 'expired' ? [] : [15000],
    'preparation consumes the original deadline; an expired grant must not launch');
  process.stdout.write(`original grant ${deadlineMode} boundary checked\n`);
} else {
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
      let failed = false;
      let lastLog = '';
      await handleTask({ readyState: 1, send(raw) {
        const event = JSON.parse(raw);
        if (event.type === 'task_log') lastLog = String(event.content).slice(-4000);
        if (event.type === 'task_progress' && event.status === 'failed') failed = true;
      } }, task, { runAgent, isAvailable });
      assert.equal(failed, false, lastLog || 'real workspace executor failed');
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
}
