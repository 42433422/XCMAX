import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import tls from 'node:tls';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { trainerArguments, trainerEnvironment, trainerPolicy, trainerRequestFilter, trainerSpec } from './promptfoo_sandbox.mjs';

const wrapper = fileURLToPath(new URL('./promptfoo_sandbox.mjs', import.meta.url));
const runtime = process.env.PROMPTFOO_SANDBOX_ENTRY;
const cli = process.env.PROMPTFOO_CLI;
const python = process.env.PROMPTFOO_PYTHON;
const pythonpath = resolve(dirname(wrapper), '../../../../成都修茈科技有限公司/MODstore_deploy');
const hostApp = realpathSync(resolve(dirname(wrapper), '../../../app'));
const key = 'synthetic-model-key', model = 'approved-model';

async function child(command, args, options) {
  const process = spawn(command, args, { ...options, stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = '', stderr = '';
  process.stdout.setEncoding('utf8').on('data', value => { stdout += value; });
  process.stderr.setEncoding('utf8').on('data', value => { stderr += value; });
  const timer = setTimeout(() => process.kill('SIGKILL'), 45000);
  try {
    const [code] = await once(process, 'close');
    return { code, stdout, stderr };
  } finally { clearTimeout(timer); }
}

async function listen(server, t, host = '127.0.0.1') {
  const sockets = new Set();
  server.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });
  server.listen(0, host);
  await once(server, 'listening');
  t.after(() => { for (const socket of sockets) socket.destroy(); server.close(); });
  return server.address().port;
}

function request(proxyPort, target, ca, body, path = '/v1/chat/completions') {
  return new Promise((resolveResponse, reject) => {
    const authority = target.hostname + ':' + (target.port || 443);
    const tunnel = http.request({ hostname: '127.0.0.1', port: proxyPort,
      method: 'CONNECT', path: authority, headers: { host: authority } });
    tunnel.once('error', reject);
    tunnel.once('connect', (response, socket) => {
      if (response.statusCode !== 200) { socket.destroy(); resolveResponse(response.statusCode); return; }
      const secure = tls.connect({ socket, ca, rejectUnauthorized: true,
        checkServerIdentity: (_host, cert) => tls.checkServerIdentity(target.hostname, cert) });
      secure.once('error', reject);
      secure.once('secureConnect', () => {
        const agent = new http.Agent({ keepAlive: false });
        agent.createConnection = () => secure;
        const call = http.request({ hostname: target.hostname, port: target.port,
          method: 'POST', path, agent, headers: { host: target.host,
            'content-type': 'application/json', 'content-length': Buffer.byteLength(body) } }, result => {
          result.resume();
          result.once('end', () => { secure.destroy(); agent.destroy(); resolveResponse(result.statusCode); });
        });
        call.once('error', reject);
        call.end(body);
      });
    });
    tunnel.end();
  });
}

test('missing SRT never starts an unsandboxed CLI', async t => {
  const root = mkdtempSync(join(tmpdir(), 'training-missing-runtime-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const result = await child(process.execPath, [wrapper, '--config', join(root, 'config.json'),
    '--output', join(root, 'result.json')], { env: { PATH: process.env.PATH,
    PROMPTFOO_CLI: cli || join(root, 'missing-cli'), PROMPTFOO_SANDBOX_ENTRY: join(root, 'missing-srt') } });
  assert.equal(result.code, 1);
  assert.match(result.stderr, /no unsandboxed evaluation fallback/);
  assert.equal(result.stdout, '');
});

test('model admission is exact and the CLI environment has no inherited credentials or cloud state', async () => {
  const spec = { endpoint: new URL('https://model.example:444/v1'), model, python: '/usr/bin/python3', pythonpath };
  const filter = trainerRequestFilter(spec, key);
  const invoke = (url, body, info = {}) => filter(new Request(url, { method: 'POST',
    headers: { 'content-type': 'application/json', authorization: 'Bearer untrusted' }, body: JSON.stringify(body) }),
  { scheme: 'https', requestTarget: '/v1/chat/completions', target: { host: 'model.example', port: 444 }, ...info });
  assert.equal((await invoke('https://model.example:444/v1/chat/completions', { model })).action, 'allow');
  for (const [url, body, info] of [
    ['https://r.promptfoo.app/', { model }, {}],
    ['https://model.example:444/other', { model }, {}],
    ['https://model.example:444/v1/chat/completions', { model: 'other' }, {}],
    ['https://model.example:444/v1/chat/completions', { model }, { scheme: 'http' }],
  ]) assert.equal((await invoke(url, body, info)).action, 'deny');
  const environment = trainerEnvironment(spec, '/tmp/training-synthetic');
  assert.equal(environment.PROMPTFOO_DISABLE_SHARING, '1');
  for (const name of ['OPENAI_API_KEY', 'XCAGI_LLM_API_KEY', 'DISPATCH_TOKEN', 'GITHUB_TOKEN',
    'PROMPTFOO_API_KEY', 'HTTP_PROXY', 'HTTPS_PROXY', 'NODE_OPTIONS']) assert.equal(environment[name], undefined);
});

for (const native of [false, true]) test(`real promptfoo uses the approved model ${native ? 'inside native SRT' : 'through the official SRT proxy'}`, {
  skip: !runtime || !cli || !python || (native && process.env.PROMPTFOO_TEST_NATIVE_SANDBOX !== '1'), timeout: 60000,
}, async t => {
  const root = mkdtempSync(join(tmpdir(), 'training-srt-contract-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const load = name => import(pathToFileURL(join(dirname(dirname(runtime)), 'dist/sandbox', name + '.js')));
  const [{ createHttpProxyServer }, { createMitmCA, disposeMitmCA }, { mintLeafCert },
    { SandboxRuntimeConfigSchema }] = await Promise.all([
    load('http-proxy'), load('mitm-ca'), load('mitm-leaf'), load('sandbox-config'),
  ]);
  const upstreamCA = createMitmCA({}), proxyCA = createMitmCA({});
  t.after(async () => { await disposeMitmCA(upstreamCA); await disposeMitmCA(proxyCA); });
  const cert = mintLeafCert(upstreamCA, '127.0.0.2');
  const received = [];
  const server = https.createServer({ cert: cert.certPem, key: cert.keyPem }, async (req, res) => {
    let text = '';
    for await (const chunk of req) text += chunk;
    const data = JSON.parse(text);
    received.push({ data, path: req.url, authorization: req.headers.authorization });
    const content = data.messages[0].content.includes('CANDIDATE_PASS') ? 'CANDIDATE_PASS' : 'baseline';
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ id: 'fixture', object: 'chat.completion', created: 0, model,
      choices: [{ index: 0, message: { role: 'assistant', content }, finish_reason: 'stop' }],
      usage: { prompt_tokens: 10, completion_tokens: 3, total_tokens: 13 } }));
  });
  const port = await listen(server, t, '127.0.0.2');
  const endpoint = new URL(`https://127.0.0.2:${port}/v1`);
  const folder = join(root, 'eval'), temp = join(root, 'workload');
  mkdirSync(folder); mkdirSync(temp);
  const provider = { id: 'openai:chat:' + model, config: { apiBaseUrl: endpoint.href, maxRetries: 0, max_tokens: 20 } };
  const config = join(folder, 'config.json'), output = join(folder, 'result.json');
  const nativeAssertion = join(folder, 'native_sdk_assertion.py');
  const privateSentinel = join(root, 'controller-only.txt');
  if (native) {
    writeFileSync(privateSentinel, 'synthetic controller data outside the workload');
    writeFileSync(nativeAssertion, `import hashlib, inspect, os, sys
from pathlib import Path
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
sys.path.insert(0, ${JSON.stringify(dirname(hostApp))})
from app.mod_sdk.file_employee_support import FileEmployeeSupport
from modstore_server.capability_trainer import _workflow_validation_hashes

def get_assert(output, context):
    source = Path(${JSON.stringify(join(hostApp, 'mod_sdk/file_employee_support.py'))})
    assert Path(inspect.getfile(FileEmployeeSupport)).resolve() == source
    hashes = _workflow_validation_hashes(business=True)
    assert hashes['FHD/app/mod_sdk/file_employee_support.py'] == hashlib.sha256(source.read_bytes()).hexdigest()
    try:
        fd = os.open(source, os.O_WRONLY)
    except OSError:
        pass
    else:
        os.close(fd)
        raise AssertionError('native SDK source must stay read-only')
    try:
        Path(${JSON.stringify(privateSentinel)}).read_bytes()
    except OSError:
        pass
    else:
        raise AssertionError('controller data must stay unreadable')
    assert 'XCAGI_LLM_API_KEY' not in os.environ
    passed = output == 'CANDIDATE_PASS'
    return {'pass': passed, 'score': int(passed),
            'reason': 'native_candidate_match' if passed else 'native_baseline_mismatch'}
`);
  }
  writeFileSync(config, JSON.stringify({ sharing: false, writeLatestResults: false,
    providers: [provider], defaultTest: { options: { provider } },
    prompts: ['BASELINE_ONLY {{task}}', 'CANDIDATE_PASS {{task}}'],
    tests: [{ vars: { task: 'synthetic fixture only' }, assert: [native
      ? { type: 'python', value: 'file://' + nativeAssertion + ':get_assert' }
      : { type: 'contains', value: 'CANDIDATE_PASS' }] }] }));
  const environment = { PATH: process.env.PATH, PROMPTFOO_CLI: cli, PROMPTFOO_SANDBOX_ENTRY: runtime,
    PROMPTFOO_PYTHON: python, PYTHONPATH: pythonpath, XCAGI_LLM_BASE_URL: endpoint.href,
    XCAGI_LLM_MODEL: model, XCAGI_LLM_API_KEY: key };
  const spec = trainerSpec({ config, output }, environment);
  const policy = SandboxRuntimeConfigSchema.parse(trainerPolicy(spec, temp, key));
  assert.deepEqual(policy.network.allowedDomains, [endpoint.host]);
  assert.equal(policy.network.strictAllowlist, true);
  assert.ok(policy.filesystem.allowRead.includes(hostApp));
  assert.ok(!policy.filesystem.allowRead.includes(dirname(hostApp)));
  assert.ok(!policy.filesystem.allowRead.includes(dirname(dirname(hostApp))));
  assert.deepEqual(policy.filesystem.allowWrite, [folder, temp]);
  let result;
  if (native) {
    result = await child(process.execPath, [wrapper, '--config', config, '--output', output], {
      cwd: folder, env: { ...environment, NODE_EXTRA_CA_CERTS: upstreamCA.certPath },
    });
  } else {
    // This verifies the actual upstream proxy/filter contract, not native OS isolation.
    const refused = [];
    const proxyPort = await listen(createHttpProxyServer({ mitmCA: proxyCA,
      filter: (targetPort, host) => {
        const allowed = policy.network.allowedDomains.includes(`${host}:${targetPort}`);
        if (!allowed) refused.push(host);
        return allowed;
      }, filterRequest: policy.network.filterRequest, requireHostMatch: true, refuseOpaqueTunnels: true,
      tlsTerminateUpstreamCA: upstreamCA.certPem }), t);
    for (const host of ['r.promptfoo.app', 'api.promptfoo.dev', 'api.promptfoo.app']) {
      assert.equal(await request(proxyPort, new URL('https://' + host), proxyCA.certPem, '{}'), 403);
    }
    assert.equal(received.length, 0);
    for (const [path, body] of [['/v1/chat/completions', { model: 'unapproved' }], ['/other', { model }]]) {
      assert.equal(await request(proxyPort, endpoint, proxyCA.certPem, JSON.stringify(body), path), 403);
    }
    assert.equal(received.length, 0);
    const proxy = `http://127.0.0.1:${proxyPort}`;
    result = await child(process.execPath, [spec.cli.path, ...trainerArguments(spec)], { cwd: folder,
      env: { ...trainerEnvironment(spec, temp), OPENAI_API_KEY: 'synthetic-placeholder',
        NODE_EXTRA_CA_CERTS: proxyCA.certPath, HTTP_PROXY: proxy, HTTPS_PROXY: proxy,
        http_proxy: proxy, https_proxy: proxy, NO_PROXY: '', no_proxy: '' },
    });
    assert.ok(refused.filter(host => host === 'r.promptfoo.app').length >= 2);
    assert.deepEqual(new Set(refused), new Set(['r.promptfoo.app', 'api.promptfoo.dev', 'api.promptfoo.app']));
  }
  assert.equal(result.code, 100, result.stdout + result.stderr);
  assert.equal(received.length, 2);
  assert.ok(received.every(row => row.path === '/v1/chat/completions'
    && row.data.model === model && row.authorization === 'Bearer ' + key));
  const rows = JSON.parse(readFileSync(output, 'utf8')).results.results;
  assert.equal(rows.filter(row => row.success).length, 1, JSON.stringify(rows, null, 2));
  assert.equal(rows.filter(row => !row.success).length, 1);
  if (native) {
    assert.equal(rows.find(row => row.success).gradingResult.componentResults[0].reason,
      'native_candidate_match');
    assert.equal(rows.find(row => !row.success).gradingResult.componentResults[0].reason,
      'native_baseline_mismatch');
  }
});
