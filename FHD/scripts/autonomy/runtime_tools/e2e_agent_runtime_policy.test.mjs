import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  effectiveToolName,
  isToolFallbackEligible,
  pausedByOpenCodePolicy,
  removeOwnWorkspace,
  requestedToolName,
  resetWorkspaceForNextTool,
  toolAttemptPlan,
  toolFallbackMode,
  toolFallbackOrder,
  withFailureCleanup,
} from './e2e_agent_runtime_policy.mjs';
import { assertOpenCodeHost, openCodePlatformConfig, runOpenCodeLive } from './opencode_agent.mjs';

test('GitHub dependency preparation never receives execution credentials', () => {
  const workflow = readFileSync(new URL('../../../.github/workflows/para-github-worker.yml', import.meta.url), 'utf8');
  const preparations = [...workflow.matchAll(/^      - name: Prepare existing Para executor\n.*?(?=^      - )/gms)];
  const executions = [...workflow.matchAll(/^      - name: Run original Para tasks without publication credentials\n.*?(?=^      - )/gms)];
  assert.equal(preparations.length, 2);
  assert.equal(executions.length, 2);
  for (const [step] of preparations) assert.doesNotMatch(step, /secrets\.|github\.token|AUTH_JSON|CONFIG_TOML|API_KEY|GATEWAY_KEY/);
  for (const [step] of executions) {
    assert.match(step, /PARA_CODEX_AUTH_JSON:.*secrets\.PARA_CODEX_AUTH_JSON/);
    assert.match(step, /PARA_CODEX_CONFIG_TOML:.*secrets\.PARA_CODEX_CONFIG_TOML/);
    assert.match(step, /CODEX_API_KEY: \$\{\{ vars\.DEVFLEET_FORCE_OPENCODE != '1' && secrets\.PARA_CODEX_API_KEY \|\| '' \}\}/);
    assert.doesNotMatch(step, /secrets\.OPENAI_API_KEY/);
    assert.match(step, /prepare_github_executor\.sh configure\s+node /);
  }
  for (const name of ['employee-workspace', 'resume-verification']) {
    const job = workflow.match(new RegExp('^  ' + name + ':\\n.*?(?=^  [a-z-]+:|$(?![\\s\\S]))', 'ms'))?.[0];
    assert.match(job, /runs-on: \$\{\{ vars\.DEVFLEET_FORCE_OPENCODE == '1' && 'ubuntu-22\.04' \|\| 'ubuntu-24\.04' \}\}/);
  }
  assert.match(workflow, /publish-candidate:\n[\s\S]*?runs-on: ubuntu-24\.04/);
  const contract = readFileSync(new URL('../../../.github/workflows/mac-control-contract.yml', import.meta.url), 'utf8');
  assert.match(contract, /runtime-contract:\n[\s\S]*?steps:\n      - uses: actions\/checkout@v4\n        with:\n          persist-credentials: false/);
});

function githubPreparation(t) {
  const root = mkdtempSync(join(tmpdir(), 'para-install-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const bin = join(root, 'bin'), home = join(root, 'home'), runtime = join(root, 'runtime');
  for (const directory of [bin, home, runtime]) mkdirSync(directory);
  writeFileSync(join(bin, 'npm'), '#!/bin/sh\ntouch "$RUNNER_TEMP/npm-called"\nexit 42\n', { mode: 0o700 });
  for (const command of ['bwrap', 'socat', 'rg']) writeFileSync(join(bin, command), '#!/bin/sh\nexit 0\n', { mode: 0o700 });
  const env = { PATH: bin + ':' + process.env.PATH, HOME: home, RUNNER_TEMP: runtime,
    PARA_CODEX_VERSION: '0.153.4', PARA_PLATFORM_POOL: '1',
    PARA_PLATFORM_GATEWAY_URL: 'https://gateway.example.test/v1' };
  const run = (mode, extra = {}) => spawnSync('bash', [
    fileURLToPath(new URL('./prepare_github_executor.sh', import.meta.url)), mode,
  ], { cwd: fileURLToPath(new URL('../../../', import.meta.url)), env: { ...env, ...extra }, encoding: 'utf8' });
  return { run, home, runtime, root, env };
}

test('dependency installation refuses credentials before starting package code', { skip: process.platform === 'win32' }, t => {
  const { run, runtime } = githubPreparation(t);
  for (const key of ['PARA_PLATFORM_GATEWAY_KEY', 'PARA_PLATFORM_GATEWAY_KEYS_JSON', 'PARA_CODEX_AUTH_JSON',
    'PARA_CODEX_CONFIG_TOML', 'CODEX_API_KEY', 'OPENCODE_API_KEY', 'GITHUB_TOKEN', 'MODSTORE_PARA_DISPATCH_TOKEN',
    'PARA_PLATFORM_APPROVED_KEYRING', 'GITHUB_PERSONAL_ACCESS_TOKEN']) {
    const result = run('install', { DEVFLEET_FORCE_OPENCODE: '1', [key]: 'fixture-install-secret' });
    assert.notEqual(result.status, 0, key);
    assert.match(result.stdout + result.stderr, /credential-free/);
    assert.doesNotMatch(result.stdout + result.stderr, /fixture-install-secret/);
    assert.equal(existsSync(join(runtime, 'npm-called')), false, key);
  }
});

test('unsupported Linux hosts stop OpenCode preparation before installers or authorization', {
  skip: process.platform !== 'linux' || /^VERSION_ID="22\.04"$/m.test(readFileSync('/etc/os-release', 'utf8')),
}, t => {
  const { run, home, runtime } = githubPreparation(t);
  for (const mode of ['install', 'configure']) {
    const result = run(mode, { DEVFLEET_FORCE_OPENCODE: '1',
      ...(mode === 'configure' ? { PARA_PLATFORM_GATEWAY_KEY: 'fixture-must-not-be-used' } : {}) });
    assert.notEqual(result.status, 0, mode);
    assert.match(result.stdout + result.stderr, /opencode_linux_host_requires_ubuntu_22_04/);
    assert.doesNotMatch(result.stdout + result.stderr, /fixture-must-not-be-used/);
    assert.equal(existsSync(join(runtime, 'npm-called')), false);
    assert.equal(existsSync(join(home, '.codex')), false);
  }
});

test('runtime authorization writes Codex config without running dependency installers', { skip: process.platform === 'win32' }, t => {
  const { run, home, runtime } = githubPreparation(t);
  let result = run('configure', { PARA_PLATFORM_GATEWAY_KEY: 'fixture-gateway-key' });
  assert.equal(result.status, 0, result.stderr);
  const config = join(home, '.codex', 'config.toml');
  assert.match(readFileSync(config, 'utf8'), /base_url = "https:\/\/gateway.example.test\/v1"/);
  assert.match(readFileSync(config, 'utf8'), /env_key = "CODEX_API_KEY"/);
  assert.doesNotMatch(readFileSync(config, 'utf8'), /fixture-gateway-key/);
  assert.equal(statSync(config).mode & 0o777, 0o600);
  const auth = JSON.stringify({ tokens: { access_token: 'fixture-login-token' } });
  result = run('configure', { PARA_PLATFORM_POOL: '0', PARA_CODEX_AUTH_JSON: auth,
    PARA_CODEX_CONFIG_TOML: 'model = "configured-model"\n' });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(readFileSync(join(home, '.codex', 'auth.json'), 'utf8'), auth);
  assert.equal(statSync(join(home, '.codex', 'auth.json')).mode & 0o777, 0o600);
  assert.equal(readFileSync(config, 'utf8'), 'model = "configured-model"\n');
  result = run('configure', { DEVFLEET_FORCE_OPENCODE: '1', PARA_PLATFORM_GATEWAY_KEY: 'fixture-opencode-key' });
  let hostError;
  try { assertOpenCodeHost(); } catch (error) { hostError = error; }
  assert.equal(result.status, hostError ? 1 : 0, result.stderr);
  if (hostError) assert.ok(result.stderr.includes(hostError.message));
  assert.equal(existsSync(join(runtime, 'npm-called')), false);
});

test('Codex configuration requires dedicated authorization and never accepts a shared key', { skip: process.platform === 'win32' }, t => {
  const { run, home, runtime } = githubPreparation(t);
  const config = 'model = "dedicated-model"\n';
  for (const extra of [{}, { OPENAI_API_KEY: 'fixture-shared-key' },
    { OPENAI_API_KEY: 'fixture-shared-key', PARA_CODEX_CONFIG_TOML: config }]) {
    const result = run('configure', { PARA_PLATFORM_POOL: '0', ...extra });
    assert.notEqual(result.status, 0);
    assert.match(result.stdout + result.stderr, /Para Codex authorization is not configured/);
    assert.doesNotMatch(result.stdout + result.stderr, /fixture-shared-key/);
    for (const file of ['auth.json', 'config.toml']) assert.equal(existsSync(join(home, '.codex', file)), false);
  }
  const result = run('configure', { PARA_PLATFORM_POOL: '0', CODEX_API_KEY: 'fixture-dedicated-key',
    PARA_CODEX_CONFIG_TOML: config });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(readFileSync(join(home, '.codex', 'config.toml'), 'utf8'), config);
  assert.equal(existsSync(join(runtime, 'npm-called')), false);
});

test('locked npm installation disables real lifecycle scripts and rejects changed integrity or CLI pins', { skip: process.platform === 'win32' }, t => {
  const { root, home, runtime, env: fixtureEnv } = githubPreparation(t);
  const env = { ...fixtureEnv, PATH: process.env.PATH, npm_config_offline: 'true' };
  const packageRoot = join(root, 'package'), source = join(root, 'source');
  const tools = join(source, 'scripts', 'autonomy', 'runtime_tools');
  const dependencies = join(tools, 'github_executor_deps', 'codex');
  mkdirSync(packageRoot);
  mkdirSync(dependencies, { recursive: true });
  writeFileSync(join(tools, 'fixture.mjs'), '// Copied by the real installer.\n');
  writeFileSync(join(packageRoot, 'package.json'), JSON.stringify({
    name: '@openai/codex', version: '0.153.4', bin: { codex: 'codex.js' },
    scripts: { postinstall: 'node postinstall.cjs' },
  }));
  writeFileSync(join(packageRoot, 'codex.js'), '#!/usr/bin/env node\nconsole.log("codex-cli 0.153.4");\n', { mode: 0o700 });
  writeFileSync(join(packageRoot, 'postinstall.cjs'),
    'require("node:fs").writeFileSync(process.env.RUNNER_TEMP + "/lifecycle-ran", "unsafe installer ran");\n');
  const packed = JSON.parse(execFileSync('npm', ['pack', '--ignore-scripts', '--offline', '--json', '--pack-destination', root],
    { cwd: packageRoot, env, encoding: 'utf8' }))[0];
  const manifest = { name: 'para-installer-fixture', dependencies: { '@openai/codex': '0.153.4' } };
  const lock = { name: manifest.name, lockfileVersion: 3, packages: {
    '': manifest,
    'node_modules/@openai/codex': { version: '0.153.4', resolved: 'file:' + join(root, packed.filename),
      integrity: packed.integrity, hasInstallScript: true, bin: { codex: 'codex.js' } },
  } };
  writeFileSync(join(dependencies, 'package.json'), JSON.stringify(manifest));
  const lockPath = join(dependencies, 'package-lock.json');
  writeFileSync(lockPath, JSON.stringify(lock));
  const install = (extra = {}) => spawnSync('bash', [
    fileURLToPath(new URL('./prepare_github_executor.sh', import.meta.url)), 'install',
  ], { cwd: source, env: { ...env, ...extra }, encoding: 'utf8' });
  let result = install();
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.equal(existsSync(join(runtime, 'lifecycle-ran')), false);
  assert.equal(existsSync(join(home, '.codex')), false);
  // Positive control: the exact same local package really contains a runnable hook.
  execFileSync('npm', ['ci', '--prefix', join(runtime, 'para-worker'), '--ignore-scripts=false', '--offline', '--no-audit', '--no-fund'],
    { env, stdio: 'pipe' });
  assert.equal(existsSync(join(runtime, 'lifecycle-ran')), true);
  rmSync(join(runtime, 'lifecycle-ran'));
  result = install({ PARA_CODEX_VERSION: '0.153.5' });
  assert.notEqual(result.status, 0);
  assert.match(result.stdout + result.stderr, /must match the reviewed dependency lock/);
  lock.packages['node_modules/@openai/codex'].integrity = 'sha512-' + Buffer.alloc(64).toString('base64');
  writeFileSync(lockPath, JSON.stringify(lock));
  result = install();
  assert.notEqual(result.status, 0);
  assert.match(result.stdout + result.stderr, /EINTEGRITY/);
  assert.equal(existsSync(join(runtime, 'lifecycle-ran')), false);
});

test('OpenCode-only policy pauses the other CLIs and scopes native config to the XCMAX gateway', () => {
  const env = { DEVFLEET_FORCE_OPENCODE: '1', DEVFLEET_FORCE_CODEX: '1',
    PARA_PLATFORM_GATEWAY_URL: 'https://xiu-ci.com/v1', PARA_OPENCODE_MODEL: 'xcmax-para-coding',
    OPENCODE_API_KEY: 'test-only-placeholder' };
  assert.equal(effectiveToolName({ env, fallback: 'codex' }), 'opencode');
  assert.equal(pausedByOpenCodePolicy('codex', env), true);
  assert.equal(pausedByOpenCodePolicy('opencode', env), false);
  const config = openCodePlatformConfig(env);
  assert.equal(config.provider.xcmax.npm, '@ai-sdk/openai');
  assert.equal(config.model, 'xcmax/xcmax-para-coding');
  assert.equal(config.provider.xcmax.models['xcmax-para-coding'].id, 'xcmax-para-coding');
  assert.deepEqual(config.provider.xcmax.whitelist, ['xcmax-para-coding']);
  assert.deepEqual(config.enabled_providers, ['xcmax']);
  assert.ok(!JSON.stringify(config).includes(env.OPENCODE_API_KEY));
  assert.throws(() => openCodePlatformConfig({ ...env, OPENCODE_API_KEY: '' }), /专用密钥/);
  assert.equal(openCodePlatformConfig({ ...env, PARA_OPENCODE_MODEL: 'vendor/model:variant' }).model, 'xcmax/vendor/model:variant');
  assert.throws(() => openCodePlatformConfig({ ...env, PARA_PLATFORM_POOL: '1', PARA_PLATFORM_MODEL: 'other' }), /专用密钥/);
});

test('OpenCode report-only sessions deny unknown tools even when no log callback is supplied', async () => {
  const root = mkdtempSync(join(tmpdir(), 'opencode-native-api-'));
  const executable = process.execPath;
  // The adapter launches `serve` in the task directory; Node runs this fixture
  // through its native executable on every platform, without a POSIX shebang.
  writeFileSync(join(root, 'serve'), String.raw`
const http = require('node:http');
require('node:fs').writeFileSync('server.pid', String(process.pid));
if (process.env.FIXTURE_LIFECYCLE === 'early-exit') process.exit(19);
process.on('SIGTERM', () => {
  if (process.env.FIXTURE_LIFECYCLE !== 'ignore-term') setTimeout(() => process.exit(0), 100);
});
let session;
const server = http.createServer(async (req, res) => {
  if (req.headers.authorization !== 'Basic ' + Buffer.from('opencode:' + process.env.OPENCODE_SERVER_PASSWORD).toString('base64')) {
    res.writeHead(401).end(); return;
  }
  let raw = ''; for await (const chunk of req) raw += chunk;
  if (req.url === '/event') { res.writeHead(200, {'content-type': 'text/event-stream'}); res.flushHeaders(); return; }
  res.setHeader('content-type', 'application/json');
  if (req.url === '/config') {
    const config = JSON.parse(process.env.OPENCODE_CONFIG_CONTENT);
    config.provider.xcmax.options.apiKey = process.env.OPENCODE_API_KEY;
    if (process.env.FIXTURE_CONFIG_OVERRIDE === 'headers') config.provider.xcmax.models['vendor/model:variant'].headers = {aUtHoRiZaTiOn:'fixture-other-key'};
    if (process.env.FIXTURE_CONFIG_OVERRIDE === 'endpoint') config.provider.xcmax.options.baseURL = 'https://other.example.test/v1';
    if (process.env.FIXTURE_CONFIG_OVERRIDE === 'key') config.provider.xcmax.options.apiKey = 'fixture-other-key';
    if (process.env.FIXTURE_CONFIG_OVERRIDE === 'model') config.provider.xcmax.models['vendor/model:variant'].id = 'other';
    res.end(JSON.stringify(config)); return;
  }
  if (req.url === '/session') { session = JSON.parse(raw); res.end(JSON.stringify({id:'fixture-session'})); return; }
  if (process.env.FIXTURE_LIFECYCLE === 'timeout') return;
  const message = JSON.parse(raw);
  res.end(JSON.stringify({info:{tokens:{input:1,output:2}},parts:[{type:'text',text:JSON.stringify({session,message})}]}));
});
server.listen(0, '127.0.0.1', () => console.log('http://127.0.0.1:' + server.address().port));
`);
  const assertStopped = () => assert.throws(
    () => process.kill(Number(readFileSync(join(root, 'server.pid'), 'utf8')), 0),
    error => error.code === 'ESRCH', 'the service must exit before the caller can release its workspace',
  );
  try {
    const env = { DEVFLEET_FORCE_OPENCODE: '1', PARA_PLATFORM_POOL: '1',
      PARA_OPENCODE_MODEL: 'vendor/model:variant', PARA_PLATFORM_MODEL: 'vendor/model:variant',
      PARA_PLATFORM_GATEWAY_URL: 'https://gateway.example.test/v1', OPENCODE_API_KEY: 'fixture-granted-key' };
    const platform = openCodePlatformConfig(env);
    env.OPENCODE_CONFIG_CONTENT = JSON.stringify(platform);
    for (const log of [() => {}, undefined]) {
      const output = JSON.parse(await runOpenCodeLive(executable, root, 'Review the existing files', env, {
        platform, timeoutMs: 5000, reportOnly: true, log,
      }));
      assertStopped();
      assert.equal(output.message.agent, 'plan');
      assert.equal(output.message.parts[0].text, 'Review the existing files');
      assert.deepEqual(output.message.model, { providerID: 'xcmax', modelID: 'vendor/model:variant' });
      assert.deepEqual(output.session.permission, [
        { permission: '*', pattern: '*', action: 'deny' },
        ...['read', 'glob', 'grep', 'list'].map(permission => ({ permission, pattern: '*', action: 'allow' })),
      ]);
    }
    for (const override of ['headers', 'endpoint', 'key', 'model']) {
      await assert.rejects(runOpenCodeLive(executable, root, 'Do not launch a model',
        { ...env, FIXTURE_CONFIG_OVERRIDE: override }, { platform, timeoutMs: 5000, reportOnly: false }),
      /opencode_platform_binding_mismatch/);
      assertStopped();
    }
    for (const mode of ['early-exit', 'timeout']) {
      await assert.rejects(runOpenCodeLive(executable, root, 'Must not finish',
        { ...env, FIXTURE_LIFECYCLE: mode }, { platform, timeoutMs: 1000, reportOnly: true }),
      mode === 'early-exit' ? /退出码 19/ : /timeout|aborted|超时/i);
      assertStopped();
    }
    await runOpenCodeLive(executable, root, 'Force-stop the service',
      { ...env, FIXTURE_LIFECYCLE: 'ignore-term' }, { platform, timeoutMs: 5000, reportOnly: true });
    assertStopped();
    await assert.rejects(runOpenCodeLive(join(root, 'missing-executable'), root, 'Never starts', env,
      { platform, timeoutMs: 1000, reportOnly: true }), { code: 'ENOENT' });
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('forced Codex overrides an explicit Cursor task assignment', () => {
  assert.equal(
    effectiveToolName({
      task: { tool: 'cursor' },
      env: { DEVFLEET_FORCE_CODEX: '1' },
    }),
    'codex',
  );
});

test('task assignment wins over device config when no force policy is active', () => {
  assert.equal(
    effectiveToolName({
      task: { tool: 'trae' },
      agentConfig: { devTool: 'cursor' },
      env: {},
    }),
    'trae',
  );
  assert.equal(requestedToolName({}, { devTool: 'cursor' }), 'cursor');
  assert.equal(effectiveToolName({ task: { tool_name: 'opencode' }, env: {} }), 'opencode');
});

test('queue callers can choose a supported fallback tool', () => {
  assert.equal(effectiveToolName({ task: {}, env: {}, fallback: 'codex' }), 'codex');
  assert.equal(effectiveToolName({ task: {}, env: {}, fallback: 'invalid' }), '');
});

test('failed workspace preparation always invokes bounded cleanup', async () => {
  const cleaned = [];
  await assert.rejects(
    withFailureCleanup(
      '/safe/workspace/task-id',
      async () => {
        throw new Error('clone failed');
      },
      (path) => cleaned.push(path),
    ),
    /clone failed/,
  );
  assert.deepEqual(cleaned, ['/safe/workspace/task-id']);
});

test('successful workspace preparation is not cleaned early', async () => {
  const cleaned = [];
  const result = await withFailureCleanup(
    '/safe/workspace/task-id',
    async () => 'ready',
    (path) => cleaned.push(path),
  );
  assert.equal(result, 'ready');
  assert.deepEqual(cleaned, []);
});

test('clone fallback removes only this task workspace directly under the root', () => {
  const root = mkdtempSync(join(tmpdir(), 'ws-')), own = join(root, 'task-a'), other = join(root, 'task-b');
  for (const dir of [own, other]) mkdirSync(join(dir, '.git'), { recursive: true });
  for (const bad of [root, `${other}/../task-a`, join(other, 'x'), join(root, '..'), 'task-a', '']) assert.equal(removeOwnWorkspace(bad, root), false);
  assert.equal(removeOwnWorkspace(own, root), true);
  assert.deepEqual([existsSync(own), existsSync(other)], [false, true]);
  rmSync(root, { recursive: true });
});

const CHAIN = { DEVFLEET_TOOL_FALLBACK_ORDER: 'codex,cursor,claude_code,trae' };

test('fallback order parses, normalises and de-duplicates supported tools only', () => {
  assert.deepEqual(toolFallbackOrder({ DEVFLEET_TOOL_FALLBACK_ORDER: ' Codex, cursor,claude-code,bogus,codex,trae ' }), ['codex', 'cursor', 'claude_code', 'trae']);
  assert.deepEqual(toolFallbackOrder({}), []);
});

test('no fallback order keeps the legacy single-tool path', () => {
  assert.equal(toolAttemptPlan({ task: { tool: 'cursor' }, env: {} }), null);
});

test('requested tool runs first, then the rest of the chain in order without repeats', () => {
  assert.deepEqual(toolAttemptPlan({ task: { tool: 'cursor' }, env: CHAIN }), ['cursor', 'codex', 'claude_code', 'trae']);
  assert.deepEqual(toolAttemptPlan({ task: { tool: 'opencode' }, env: CHAIN }), ['opencode', 'codex', 'cursor', 'claude_code', 'trae']);
  assert.deepEqual(toolAttemptPlan({ task: {}, env: CHAIN }), ['codex', 'cursor', 'claude_code', 'trae']);
  assert.deepEqual(toolAttemptPlan({ task: { tool: 'codex' }, env: CHAIN }), ['codex', 'cursor', 'claude_code', 'trae']);
});

test('tools that are not installed are skipped', () => {
  const installed = new Set(['codex', 'trae']);
  assert.deepEqual(
    toolAttemptPlan({ task: { tool: 'cursor' }, env: CHAIN, isAvailable: (tool) => installed.has(tool) }),
    ['codex', 'trae'],
  );
  assert.deepEqual(toolAttemptPlan({ task: {}, env: CHAIN, isAvailable: () => false }), []);
});

test('a DEVFLEET_FORCE_* switch still overrides the chain', () => {
  assert.equal(toolAttemptPlan({ task: { tool: 'codex' }, env: { ...CHAIN, DEVFLEET_FORCE_CURSOR: '1' } }), null);
  assert.equal(effectiveToolName({ task: { tool: 'codex' }, env: { ...CHAIN, DEVFLEET_FORCE_CURSOR: '1' } }), 'cursor');
});

test('provider mode falls back only on quota, login, billing, rate-limit, timeout or provider errors', () => {
  assert.equal(toolFallbackMode({}), 'provider');
  assert.equal(toolFallbackMode({ DEVFLEET_TOOL_FALLBACK_ON: 'ANY' }), 'any');
  for (const text of [
    'You have an unpaid invoice. Please update your payment method.',
    "ERROR: You've hit your usage limit. Try again later.",
    'Error: not logged in. Please run codex login',
    'HTTP 401 Unauthorized',
    '429 Too Many Requests',
    'request timed out',
    'cursor exited with code null (timed out)\ntimed out',
    'trae 失败: failed to create agent: failed to create agent: Models is required',
  ]) assert.equal(isToolFallbackEligible(text, 'provider'), true, text);
  for (const text of [
    'AssertionError: expected 2 to equal 3',
    'SyntaxError: Unexpected token',
    'safety policy violation: unauthorized content',
    'failed to create agent: Models is required; permission denied',
    '',
  ]) assert.equal(isToolFallbackEligible(text, 'provider'), false, text);
  assert.equal(isToolFallbackEligible('AssertionError: expected 2 to equal 3', 'any'), true);
});

test('workspace is reset in place to the task base between tool attempts', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'chain-'));
  const run = (args) => execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', ...args], { cwd: dir, encoding: 'utf8' }).trim();
  try {
    run(['init', '-q', '-b', 'main']);
    run(['config', 'core.autocrlf', 'false']);
    writeFileSync(join(dir, 'a.txt'), 'base\n');
    run(['add', 'a.txt']);
    run(['commit', '-q', '-m', 'base']);
    const baseHead = run(['rev-parse', 'HEAD']);
    run(['checkout', '-q', '-b', 'devfleet/work']);
    mkdirSync(join(dir, '.devfleet'));
    writeFileSync(join(dir, '.devfleet', 'TASK.md'), 'task\n');
    writeFileSync(join(dir, '.git', 'info', 'exclude'), '.devfleet/\n');
    // 上一个工具留下的半成品：一个提交 + 未提交改动 + 新文件
    writeFileSync(join(dir, 'a.txt'), 'tool commit\n');
    run(['commit', '-q', '-am', 'half done']);
    writeFileSync(join(dir, 'a.txt'), 'dirty\n');
    writeFileSync(join(dir, 'new.txt'), 'untracked\n');

    await resetWorkspaceForNextTool(async (cwd, args) => execFileSync('git', args, { cwd, encoding: 'utf8' }), dir, { work_branch: 'devfleet/work' }, baseHead);

    assert.equal(run(['rev-parse', 'HEAD']), baseHead);
    assert.equal(run(['rev-parse', '--abbrev-ref', 'HEAD']), 'devfleet/work');
    assert.equal(run(['status', '--porcelain']), '');
    assert.equal(readFileSync(join(dir, 'a.txt'), 'utf8'), 'base\n');
    assert.equal(existsSync(join(dir, 'new.txt')), false);
    assert.equal(existsSync(join(dir, '.devfleet', 'TASK.md')), true);
    await assert.rejects(resetWorkspaceForNextTool(async () => '', dir, { work_branch: 'x' }, ''), /no task base/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
