import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { once } from 'node:events';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import test from 'node:test';
import tls from 'node:tls';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { controllerSettings } from './opencode_sandbox_controller.mjs';
import { assertOpenCodeHost, openCodePlatformConfig, runOpenCodeLive, sandboxSettings } from './opencode_agent.mjs';

const runtime = process.env.PARA_TEST_SANDBOX_ENTRY;
const key = 'fixture-real-key-that-must-never-enter-model-input';
const placeholder = 'xcmax-placeholder-fixture';
const model = 'approved-model';

async function listen(server, t, host = '127.0.0.1') {
  const sockets = new Set();
  server.on('connection', socket => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });
  server.listen(0, host);
  await once(server, 'listening');
  t.after(() => {
    for (const socket of sockets) socket.destroy();
    server.close();
  });
  return server.address().port;
}

function throughProxy(proxyPort, gateway, ca, { method = 'POST', path = '/v1/responses',
  body = JSON.stringify({ model, input: placeholder }), host = gateway.host,
  connectHost = gateway.host, headers = {}, cleartext = false } = {}) {
  return new Promise((resolve, reject) => {
    let secure, agent;
    const finish = value => {
      secure?.destroy();
      agent?.destroy();
      resolve(value);
    };
    const fail = error => { secure?.destroy(); agent?.destroy(); reject(error); };
    const collect = response => {
      let text = '';
      response.setEncoding('utf8');
      response.on('data', chunk => { text += chunk; });
      response.once('error', fail);
      response.once('end', () => finish({ status: response.statusCode, headers: response.headers, text }));
    };
    const requestHeaders = { host, 'content-type': 'application/json',
      authorization: 'Bearer ' + placeholder, ...headers,
      ...(body ? { 'content-length': Buffer.byteLength(body) } : {}) };
    if (cleartext) {
      const request = http.request({ hostname: '127.0.0.1', port: proxyPort,
        method, path: 'https://' + gateway.host + path, headers: requestHeaders }, collect);
      request.once('error', fail);
      request.end(body);
      return;
    }
    const tunnel = http.request({ hostname: '127.0.0.1', port: proxyPort,
      method: 'CONNECT', path: connectHost, headers: { host: connectHost } });
    tunnel.once('error', fail);
    tunnel.once('connect', (response, socket, head) => {
      if (response.statusCode !== 200) {
        socket.destroy();
        finish({ status: response.statusCode, headers: response.headers, text: head.toString() });
        return;
      }
      assert.equal(head.length, 0);
      secure = tls.connect({ socket, ca, rejectUnauthorized: true,
        checkServerIdentity: (_host, certificate) => tls.checkServerIdentity(gateway.hostname, certificate) });
      secure.once('error', fail);
      secure.once('secureConnect', () => {
        agent = new http.Agent({ keepAlive: false });
        agent.createConnection = () => secure;
        const request = http.request({ hostname: gateway.hostname, port: gateway.port,
          method, path, headers: requestHeaders, agent }, collect);
        request.once('error', fail);
        request.end(body);
      });
    });
    tunnel.end();
  });
}

test('official SRT TLS proxy binds header-only credentials to admitted requests', {
  skip: !runtime, timeout: 30000,
}, async t => {
  const root = dirname(dirname(runtime));
  assert.equal(JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version, '0.0.83');
  const load = name => import(pathToFileURL(join(root, 'dist', 'sandbox', name + '.js')));
  const [{ SandboxRuntimeConfigSchema }, { createHttpProxyServer },
    { createMitmCA, disposeMitmCA }, { mintLeafCert }] = await Promise.all([
    load('sandbox-config'), load('http-proxy'), load('mitm-ca'), load('mitm-leaf'),
  ]);
  const ca = createMitmCA({});
  const upstreamCA = createMitmCA({});
  t.after(async () => { await disposeMitmCA(ca); await disposeMitmCA(upstreamCA); });
  const cert = mintLeafCert(upstreamCA, '127.0.0.1');
  const requests = [];
  const upstream = https.createServer({ cert: cert.certPem, key: cert.keyPem }, async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    requests.push({ headers: req.headers, body, path: req.url });
    // A Responses-like echo of MODEL INPUT, not a fictitious echo of auth headers.
    // A generic SRT mask would replace the placeholder in this body with key.
    const output = JSON.stringify({ output: body ? JSON.parse(body).input : 'models' });
    res.writeHead(200, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(output),
      'x-api-key': key, 'set-cookie': 'fixture=not-for-workload' });
    res.end(output);
  });
  const upstreamPort = await listen(upstream, t);
  const gateway = new URL(`https://127.0.0.1:${upstreamPort}/v1`);
  const settings = controllerSettings({ gateway: gateway.href, model, settings: {
    filesystem: { denyRead: ['/'], allowWrite: [], denyWrite: [] },
  } }, key);
  const policy = SandboxRuntimeConfigSchema.parse(settings);
  assert.deepEqual(policy.credentials.envVars, [{ name: 'OPENCODE_API_KEY', mode: 'deny' }]);
  // The old host:port mask configuration is not even a valid official schema.
  assert.equal(SandboxRuntimeConfigSchema.safeParse({ ...settings, credentials: {
    envVars: [{ name: 'OPENCODE_API_KEY', mode: 'mask', injectHosts: [gateway.host] }],
  } }).success, false);
  const proxyOptions = {
    filter: (port, host) => host === gateway.hostname && port === upstreamPort,
    mitmCA: ca, filterRequest: policy.network.filterRequest,
    requireHostMatch: policy.network.requireHostMatch,
    refuseOpaqueTunnels: policy.network.refuseOpaqueTunnels,
    stripResponseHeaders: policy.network.stripResponseHeaders,
    // A test-specific trust ROOT, not rejectUnauthorized=false. Both client and
    // SRT's upstream verify the hostname and chain on actual TLS connections.
    tlsTerminateUpstreamCA: upstreamCA.certPem,
  };
  const proxyPort = await listen(createHttpProxyServer(proxyOptions), t);

  await t.test('only Authorization receives the real key; prompt and returned body retain placeholder', async () => {
    const reply = await throughProxy(proxyPort, gateway, ca.certPem, {
      headers: { 'x-forwarded-host': 'wrong.example', 'x-api-key': placeholder, cookie: 'session=untrusted' },
    });
    assert.equal(reply.status, 200);
    assert.equal(JSON.parse(reply.text).output, placeholder);
    assert.equal(reply.text.includes(key), false);
    assert.equal(reply.headers['x-api-key'], undefined);
    assert.equal(reply.headers['set-cookie'], undefined);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].headers.authorization, 'Bearer ' + key);
    assert.equal(requests[0].headers['x-forwarded-host'], undefined);
    assert.equal(requests[0].headers['x-api-key'], undefined);
    assert.equal(requests[0].headers.cookie, undefined);
    assert.equal(JSON.parse(requests[0].body).input, placeholder);
  });
  await t.test('only exact models GET is admitted without a body', async () => {
    const reply = await throughProxy(proxyPort, gateway, ca.certPem, { method: 'GET', path: '/v1/models', body: '' });
    assert.equal(reply.status, 200);
    assert.equal(requests.at(-1).headers.authorization, 'Bearer ' + key);
  });
  await t.test('wrong route, model, method, host and plaintext never reach the upstream', async () => {
    const count = requests.length;
    for (const options of [
      { path: '/v1/responses?echo=authorization' }, { path: '/debug/headers' },
      { path: '/v1/chat/completions' }, { path: '/v1/a/../responses' },
      { body: JSON.stringify({ model: 'unapproved', input: placeholder }) },
      { body: '{"model":' }, { method: 'DELETE' }, { method: 'TRACE', body: '' },
      { method: 'GET', path: '/v1/models', body: '{}' },
      { headers: { 'content-encoding': 'gzip' } },
      { host: 'wrong.example' }, { connectHost: 'wrong.example:443' }, { cleartext: true },
    ]) {
      const reply = await throughProxy(proxyPort, gateway, ca.certPem, options);
      assert.ok([400, 403, 405, 421].includes(reply.status), JSON.stringify({ options, reply }));
      assert.equal(reply.text.includes(key), false);
    }
    assert.equal(requests.length, count);
  });
  await t.test('a certificate outside the configured upstream trust root receives no credentials', async () => {
    const untrustedPort = await listen(createHttpProxyServer({ ...proxyOptions,
      tlsTerminateUpstreamCA: ca.certPem }), t);
    const count = requests.length;
    const reply = await throughProxy(untrustedPort, gateway, ca.certPem);
    assert.equal(reply.status, 502);
    assert.equal(requests.length, count);
    assert.equal(reply.text.includes(key), false);
  });
});

const openCodeBinary = process.env.PARA_TEST_OPENCODE_BINARY || (runtime
  ? resolve(dirname(dirname(runtime)), '../../opencode-linux-x64-baseline/bin/opencode') : '');
for (const native of [false, true]) test(`real OpenCode 1.19.6 Responses SSE ${native ? 'inside admitted native sandbox' : 'through official TLS proxy'}`, {
  skip: !runtime || !existsSync(openCodeBinary) || (native && (process.platform !== 'linux'
    || process.env.PARA_TEST_OPENCODE_HOST !== 'supported')), timeout: 60000,
}, async t => {
  if (native) assertOpenCodeHost(); // Never weaken or mock the actual host gate.
  assert.equal(execFileSync(openCodeBinary, ['--version'], { encoding: 'utf8', timeout: 10000 }).trim(), '1.19.6');
  const root = mkdtempSync(join(tmpdir(), 'opencode-real-protocol-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const load = name => import(pathToFileURL(join(dirname(dirname(runtime)), 'dist', 'sandbox', name + '.js')));
  const [{ createHttpProxyServer }, { createMitmCA, disposeMitmCA }, { mintLeafCert }] = await Promise.all([
    load('http-proxy'), load('mitm-ca'), load('mitm-leaf'),
  ]);
  const upstreamCA = createMitmCA({});
  t.after(() => disposeMitmCA(upstreamCA));
  const leaf = mintLeafCert(upstreamCA, '127.0.0.2');
  const requests = [];
  const output = 'READY ' + placeholder;
  const upstream = https.createServer({ cert: leaf.certPem, key: leaf.keyPem }, async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    const parsed = JSON.parse(body);
    requests.push({ path: req.url, authorization: req.headers.authorization, body: parsed });
    const item = { id: 'msg_fixture', type: 'message', role: 'assistant', status: 'completed',
      content: [{ type: 'output_text', text: output, annotations: [] }] };
    const response = { id: 'resp_fixture', object: 'response', model, created_at: 1, status: 'completed',
      output: [item], usage: { input_tokens: 20, output_tokens: 4, total_tokens: 24,
        input_tokens_details: { cached_tokens: 0 }, output_tokens_details: { reasoning_tokens: 0 } } };
    if (!parsed.stream) {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify(response));
      return;
    }
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
    const event = (type, fields) => res.write('event: ' + type + '\ndata: ' + JSON.stringify({ type, ...fields }) + '\n\n');
    event('response.created', { response: { ...response, status: 'in_progress', output: [], usage: null } });
    event('response.output_item.added', { output_index: 0, item: { ...item, status: 'in_progress', content: [] } });
    event('response.content_part.added', { item_id: item.id, output_index: 0, content_index: 0, part: { type: 'output_text', text: '', annotations: [] } });
    event('response.output_text.delta', { item_id: item.id, output_index: 0, content_index: 0, delta: output });
    event('response.output_text.done', { item_id: item.id, output_index: 0, content_index: 0, text: output });
    event('response.output_item.done', { output_index: 0, item });
    event('response.completed', { response });
    res.end();
  });
  // 127.0.0.2 is outside SRT's exact localhost NO_PROXY list. The native test
  // must cross the host proxy because its private loopback has no upstream.
  const upstreamPort = await listen(upstream, t, '127.0.0.2');
  const gateway = `https://127.0.0.2:${upstreamPort}/v1`;
  const workspace = join(root, 'workspace'), workloadTemp = join(root, 'workload'), controlTemp = join(root, 'control');
  for (const path of [workspace, workloadTemp, controlTemp]) mkdirSync(path);
  const env = { PATH: process.env.PATH, HOME: workloadTemp, TMPDIR: workloadTemp,
    XDG_CONFIG_HOME: join(workloadTemp, 'config'), XDG_CACHE_HOME: join(workloadTemp, 'cache'),
    XDG_DATA_HOME: join(workloadTemp, 'data'), XDG_STATE_HOME: join(workloadTemp, 'state'),
    OPENCODE_API_KEY: placeholder, PARA_OPENCODE_MODEL: model, PARA_PLATFORM_GATEWAY_URL: gateway,
    OPENCODE_DISABLE_PROJECT_CONFIG: 'true', OPENCODE_DISABLE_AUTOUPDATE: 'true', OPENCODE_DISABLE_MODELS_FETCH: 'true',
    OPENCODE_PERMISSION: JSON.stringify({ '*': 'deny', read: 'allow', glob: 'allow', grep: 'allow', list: 'allow' }) };
  const platform = openCodePlatformConfig(env);
  env.OPENCODE_CONFIG_CONTENT = JSON.stringify(platform);
  const prompt = 'Reply READY. Keep this literal input marker unchanged: ' + placeholder;
  let result;
  if (native) {
    const entry = fileURLToPath(new URL('./opencode_agent.mjs', import.meta.url));
    const controller = fileURLToPath(new URL('./opencode_sandbox_controller.mjs', import.meta.url));
    const settings = sandboxSettings(workspace, workloadTemp, openCodeBinary, process.execPath, new URL(gateway), true, runtime);
    const child = spawn(process.execPath, [controller], { cwd: workspace, stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...env, OPENCODE_API_KEY: key, TMPDIR: controlTemp, NODE_EXTRA_CA_CERTS: upstreamCA.certPath } });
    t.after(() => child.kill('SIGKILL'));
    let stdout = '', stderr = '';
    child.stdout.setEncoding('utf8').on('data', chunk => { stdout += chunk; });
    child.stderr.setEncoding('utf8').on('data', chunk => { stderr += chunk; });
    const closed = once(child, 'close');
    child.stdin.end(JSON.stringify({ runtime, settings, gateway, model, timeoutMs: 40000,
      command: [process.execPath, entry, '--sandbox-worker'],
      workload: { executable: openCodeBinary, prompt, reportOnly: true, timeoutMs: 35000,
        workloadPath: env.PATH, workloadTemp } }));
    const [code] = await closed;
    assert.equal(code, 0, stdout + stderr);
    result = stdout.trim().split('\n').map(line => { try { return JSON.parse(line); } catch { return {}; } })
      .find(row => row.type === 'result')?.text;
  } else {
    const ca = createMitmCA({});
    t.after(() => disposeMitmCA(ca));
    const policy = controllerSettings({ settings: {}, gateway, model }, key);
    const proxyPort = await listen(createHttpProxyServer({ mitmCA: ca,
      filter: (port, host) => host === '127.0.0.2' && port === upstreamPort,
      filterRequest: policy.network.filterRequest, requireHostMatch: true, refuseOpaqueTunnels: true,
      tlsTerminateUpstreamCA: upstreamCA.certPem }), t);
    const proxy = `http://127.0.0.1:${proxyPort}`;
    Object.assign(env, { HTTP_PROXY: proxy, HTTPS_PROXY: proxy, http_proxy: proxy, https_proxy: proxy,
      NO_PROXY: 'localhost,127.0.0.1', no_proxy: 'localhost,127.0.0.1',
      NODE_EXTRA_CA_CERTS: ca.certPath, SSL_CERT_FILE: ca.certPath });
    result = await runOpenCodeLive(openCodeBinary, workspace, prompt, env, { timeoutMs: 40000, reportOnly: true, platform });
  }
  assert.equal(result, output);
  assert.ok(requests.length >= 1);
  assert.ok(requests.every(row => row.path === '/v1/responses' && row.body.model === model && row.authorization === 'Bearer ' + key));
  assert.ok(requests.some(row => row.body.stream === true));
  assert.ok(requests.some(row => JSON.stringify(row.body).includes(placeholder)));
  assert.ok(requests.every(row => !JSON.stringify(row.body).includes(key)));
});

// Real child processes and OS signals; only the SRT lifecycle hook is a fixture.
// Native filesystem/PID/seccomp enforcement stays in opencode_agent.test.mjs.
for (const mode of ['TERM', 'KILL after ignored TERM', 'failed initialization']) test(`controller safely releases sandbox resources after ${mode}`, {
  skip: process.platform === 'win32', timeout: 10000,
}, async t => {
  const ignoreTerm = mode === 'KILL after ignored TERM';
  const failedInit = mode === 'failed initialization';
  const root = mkdtempSync(join(tmpdir(), 'opencode-controller-lifecycle-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const runtimeRoot = join(root, 'runtime');
  mkdirSync(join(runtimeRoot, 'dist'), { recursive: true });
  writeFileSync(join(runtimeRoot, 'package.json'), JSON.stringify({ name: '@anthropic-ai/sandbox-runtime', version: '0.0.83', type: 'module' }));
  writeFileSync(join(runtimeRoot, 'dist', 'cli.js'), '');
  const boundary = join(root, 'deny-boundary');
  const workerPid = join(root, 'worker.pid');
  const receipts = join(root, 'cleanup.jsonl');
  writeFileSync(join(runtimeRoot, 'dist', 'index.js'), `
import fs from 'node:fs';
const boundary = ${JSON.stringify(boundary)}, pidFile = ${JSON.stringify(workerPid)}, receipts = ${JSON.stringify(receipts)};
export const SandboxRuntimeConfigSchema = { parse: value => value };
export const SandboxManager = {
  async initialize() {
    fs.writeFileSync(boundary, 'deny-active');
    const premature = () => { fs.appendFileSync(receipts, JSON.stringify({premature:true})+'\\n'); fs.unlinkSync(boundary); };
    process.once('SIGINT', premature); process.once('SIGTERM', premature);
    process.once('exit', () => fs.appendFileSync(receipts, JSON.stringify({exitCleanup:true})+'\\n'));
    ${failedInit ? "throw new Error('fixture_initialization_failed');" : ''}
  },
  async wrapWithSandbox(command) { return command; },
  getMitmCA() { return {keyPath: boundary}; },
  async reset() {
    let alive = false;
    if (fs.existsSync(pidFile)) { try { process.kill(Number(fs.readFileSync(pidFile, 'utf8')), 0); alive = true; } catch {} }
    fs.appendFileSync(receipts, JSON.stringify({reset:true,alive,boundary:fs.existsSync(boundary)})+'\\n');
    fs.rmSync(boundary,{force:true});
  }
};`);
  const worker = join(root, 'worker.mjs');
  writeFileSync(worker, `
import fs from 'node:fs';
let raw = ''; for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw);
if (process.env.OPENCODE_API_KEY || !input.credentialPlaceholder || input.sandboxPrivateKeyPath !== ${JSON.stringify(boundary)}) process.exit(90);
fs.writeFileSync(${JSON.stringify(workerPid)}, String(process.pid));
process.on('SIGTERM', () => { ${ignoreTerm ? '' : 'process.exit(0);'} });
console.log('READY');
setInterval(() => { if (!fs.existsSync(${JSON.stringify(boundary)})) process.exit(91); }, 10);
`);
  const harness = join(root, 'harness.mjs');
  const controllerUrl = new URL('./opencode_sandbox_controller.mjs', import.meta.url).href;
  writeFileSync(harness, `
import fs from 'node:fs';
import { runSandboxController } from ${JSON.stringify(controllerUrl)};
process.on('SIGTERM', () => fs.appendFileSync(${JSON.stringify(receipts)}, JSON.stringify({externalListener:true})+'\\n'));
let raw = ''; for await (const chunk of process.stdin) raw += chunk;
process.exitCode = await runSandboxController(JSON.parse(raw));
`);
  const child = spawn(process.execPath, [harness], { env: { ...process.env, OPENCODE_API_KEY: key }, stdio: ['pipe', 'pipe', 'pipe'] });
  t.after(() => child.kill('SIGKILL'));
  let stderr = '';
  child.stderr.setEncoding('utf8').on('data', chunk => { stderr += chunk; });
  const closed = once(child, 'close');
  const ready = failedInit ? Promise.resolve() : new Promise((resolveReady, reject) => {
    const lines = createInterface({ input: child.stdout });
    lines.on('line', line => { if (line === 'READY') resolveReady(); });
    child.once('exit', () => reject(new Error('worker not started: ' + stderr)));
  });
  child.stdin.end(JSON.stringify({ runtime: join(runtimeRoot, 'dist', 'cli.js'), settings: {},
    gateway: 'https://gateway.example/v1', model, command: [process.execPath, worker],
    workload: {}, timeoutMs: 7000 }));
  await ready;
  const started = Date.now();
  if (!failedInit) child.kill('SIGTERM');
  const [code] = await closed;
  assert.equal(code, 1, stderr);
  assert.ok(Date.now() - started < 5000, 'controller must finish inside its parent teardown window');
  const records = readFileSync(receipts, 'utf8').trim().split('\n').map(line => JSON.parse(line));
  assert.deepEqual(records.filter(row => row.reset), [{ reset: true, alive: false, boundary: true }]);
  assert.equal(records.some(row => row.externalListener), !failedInit);
  assert.ok(records.some(row => row.exitCleanup));
  assert.equal(records.some(row => row.premature), false);
  assert.equal(existsSync(boundary), false);
});
