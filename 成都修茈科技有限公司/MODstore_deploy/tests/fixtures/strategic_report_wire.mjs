// Run the real pinned OpenCode protocol against the test's owned MODstore route.
// This loopback-only harness replaces the native sandbox launch on unsupported
// test hosts; production still calls runOpenCodeAgent and its fixed SRT boundary.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const { runGithubExecutor } = await import(pathToFileURL(join(process.env.REPORT_RUNTIME_TOOLS, 'github_para_executor.mjs')));
const { runStrategicReport } = await import(pathToFileURL(join(process.env.REPORT_RUNTIME_TOOLS, 'strategic_report_controller.mjs')));
const { openCodePlatformConfig, runOpenCodeLive } = await import(pathToFileURL(join(process.env.REPORT_RUNTIME_TOOLS, 'opencode_agent.mjs')));
const env = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const loopback = process.env.REPORT_LOOPBACK;
const forward = (url, options) => {
  const parsed = new URL(url);
  assert.equal(parsed.origin, 'https://xiu-ci.com');
  return fetch(loopback + parsed.pathname, options);
};
const runAgent = async (cwd, prompt, options) => {
  assert.equal(options.reportOnly, true);
  assert.equal(options.env.MODSTORE_PARA_DISPATCH_TOKEN, undefined);
  const config = openCodePlatformConfig(options.env);
  config.provider.xcmax.options.baseURL = loopback + new URL(config.provider.xcmax.options.baseURL).pathname;
  const modelEnv = { ...options.env, OPENCODE_CONFIG_CONTENT: JSON.stringify(config),
    XDG_CONFIG_HOME: join(cwd, '.wire', 'config'), XDG_CACHE_HOME: join(cwd, '.wire', 'cache'),
    XDG_DATA_HOME: join(cwd, '.wire', 'data'), XDG_STATE_HOME: join(cwd, '.wire', 'state'),
    OPENCODE_DISABLE_PROJECT_CONFIG: 'true', OPENCODE_DISABLE_AUTOUPDATE: 'true', OPENCODE_DISABLE_MODELS_FETCH: 'true',
    OPENCODE_PERMISSION: JSON.stringify({ '*': 'deny', read: 'allow', glob: 'allow', grep: 'allow', list: 'allow' }) };
  return runOpenCodeLive(process.env.PARA_TEST_OPENCODE_BINARY, cwd, prompt, modelEnv,
    { ...options, platform: config, timeoutMs: Math.min(options.timeoutMs, 45000) });
};
const code = await runGithubExecutor({ env, fetchStatus: forward,
  verifyFeedbackIsolation: () => {}, // Host/SRT itself is covered by the existing native host suite.
  runReport: options => runStrategicReport({ ...options, runAgent }) });
assert.equal(code, 0);
process.stdout.write('ordinary remote report controller completed\n');
