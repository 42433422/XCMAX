import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readlinkSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { assertLinuxWorkloadIsolation, assertMaskedCredential, assertPrivateKeyUnreadable, assertOpenCodeHost, isOpenCodeReady, openCodeSandboxEntry, runOpenCodeAgent } from './opencode_agent.mjs';

const sandbox = process.env.PARA_TEST_SANDBOX_ENTRY;

test('workload refuses raw credentials or a readable proxy private key', () => {
  const digest = createHash('sha256').update('fixture-key').digest('hex');
  assert.doesNotThrow(() => assertMaskedCredential('xcmax-placeholder-test', digest));
  for (const value of [undefined, '', 'fixture-key']) {
    assert.throws(() => assertMaskedCredential(value, digest), /non_exportable/);
  }
  assert.throws(() => assertMaskedCredential('placeholder', ''), /non_exportable/);
  assert.throws(() => assertPrivateKeyUnreadable(fileURLToPath(import.meta.url)), /private_key_readable/);
  assert.throws(() => assertPrivateKeyUnreadable(undefined), /boundary_missing/);
  assert.doesNotThrow(() => assertPrivateKeyUnreadable(join(tmpdir(), 'missing-xcmax-control-key', 'ca.key')));
});

test('Linux admission requires Ubuntu 22.04, unrestricted user namespaces and a non-root caller', () => {
  const host = { platform: 'linux', release: 'ID=ubuntu\nVERSION_ID="22.04"\n', restricted: false, uid: 1000, euid: 1000 };
  assert.doesNotThrow(() => assertOpenCodeHost(host));
  for (const version of ['24.04', '25.04', '26.04', '22.10']) {
    assert.throws(() => assertOpenCodeHost({ ...host, release: host.release.replace('22.04', version) }), /host_requires_ubuntu_22_04/);
  }
  assert.throws(() => assertOpenCodeHost({ ...host, release: host.release.replace('ubuntu', 'debian') }), /host_requires_ubuntu_22_04/);
  assert.throws(() => assertOpenCodeHost({ ...host, restricted: true }), /without_userns_restrictions/);
  for (const identity of [{ uid: 0, euid: 0 }, { uid: 1000, euid: 0 }, { uid: null, euid: null }]) {
    assert.throws(() => assertOpenCodeHost({ ...host, ...identity }), /requires_non_root/);
  }
  assert.doesNotThrow(() => assertOpenCodeHost({ platform: 'darwin' }));
  assert.throws(() => assertOpenCodeHost({ platform: 'win32' }), /host_requires/);
});

test('workloads reject ambient capabilities or outer procfs and require NNP and seccomp', () => {
  const status = 'CapEff:\t00000000\nCapPrm:\t00000000\nCapAmb:\t00000000\nCapInh:\t00000000\nNoNewPrivs:\t1\nSeccomp:\t2\nNSpid:\t42\n';
  assert.doesNotThrow(() => assertLinuxWorkloadIsolation(status));
  for (const name of ['CapEff', 'CapPrm', 'CapAmb', 'CapInh']) {
    assert.throws(() => assertLinuxWorkloadIsolation(status.replace(name + ':\t00000000', name + ':\t00200000')), /isolation_required/);
  }
  for (const [before, after] of [['NoNewPrivs:\t1', 'NoNewPrivs:\t0'], ['Seccomp:\t2', 'Seccomp:\t0'],
    ['NSpid:\t42', 'NSpid:\t12\t42'], ['NSpid:\t42', '']]) {
    assert.throws(() => assertLinuxWorkloadIsolation(status.replace(before, after)), /isolation_required/);
  }
});

test('unavailable sandbox or gateway cannot advertise OpenCode or start a task', async () => {
  const env = { DEVFLEET_OPENCODE_AGENT: process.execPath,
    DEVFLEET_OPENCODE_SANDBOX_ENTRY: join(tmpdir(), 'missing-para-sandbox', 'cli.js') };
  assert.equal(isOpenCodeReady(env), false);
  assert.equal(openCodeSandboxEntry(env), undefined);
  await assert.rejects(runOpenCodeAgent(tmpdir(), 'Must not execute', {
    env, timeoutMs: 1000, reportOnly: true,
  }), /沙箱|opencode_.*(?:host|non_root)/);
  if (sandbox) assert.equal(isOpenCodeReady({ ...env, DEVFLEET_OPENCODE_SANDBOX_ENTRY: sandbox }), false);
});

test(process.env.PARA_TEST_OPENCODE_HOST === 'unsupported'
  ? 'Ubuntu 26 refuses OpenCode before preparing a task or starting any executor'
  : 'isolated OpenCode rejects interactive approval and finishes a report-only session', {
  skip: !sandbox || process.platform === 'win32',
}, async t => {
  const root = mkdtempSync(join(realpathSync(tmpdir()), 'para-opencode-contract-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const cwd = join(root, 'workspace');
  mkdirSync(cwd);
  const protectedFile = join(root, 'outside.txt');
  writeFileSync(protectedFile, 'untouched');
  const executable = join(root, 'fake-opencode');
  if (process.env.PARA_TEST_OPENCODE_HOST === 'unsupported') {
    assert.equal(process.platform, 'linux');
    assert.match(readFileSync('/etc/os-release', 'utf8'), /^VERSION_ID="26\.04"$/m);
    assert.equal(JSON.parse(readFileSync(join(dirname(sandbox), '..', 'package.json'), 'utf8')).version, '0.0.83');
    const marker = join(root, 'executor-started');
    writeFileSync(executable, `#!${process.execPath}\nrequire('node:fs').writeFileSync(${JSON.stringify(marker)}, 'unexpected');\n`, { mode: 0o700 });
    const env = { PATH: process.env.PATH, DEVFLEET_OPENCODE_AGENT: executable,
      DEVFLEET_OPENCODE_SANDBOX_ENTRY: sandbox, OPENCODE_API_KEY: 'fixture-model-key',
      PARA_PLATFORM_GATEWAY_URL: 'https://example.invalid/v1', PARA_OPENCODE_MODEL: 'coding' };
    assert.equal(isOpenCodeReady(env), false);
    assert.equal(openCodeSandboxEntry(env), undefined);
    await assert.rejects(runOpenCodeAgent(cwd, 'Must not execute', { env, timeoutMs: 1000, reportOnly: true }),
      /opencode_linux_host_requires_ubuntu_22_04_without_userns_restrictions/);
    const result = spawnSync(process.execPath, [fileURLToPath(new URL('./opencode_agent.mjs', import.meta.url)), '--task'], {
      cwd, env, encoding: 'utf8', input: JSON.stringify({ executable, prompt: 'Must not execute', timeoutMs: 1000, reportOnly: true }),
    });
    assert.equal(result.status, 1, result.stderr);
    assert.match(result.stdout, /opencode_linux_host_requires_ubuntu_22_04_without_userns_restrictions/);
    assert.equal(existsSync(marker), false);
    return;
  }
  assertOpenCodeHost();
  writeFileSync(executable, `#!${process.execPath}
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
assert.ok(process.env.OPENCODE_API_KEY);
assert.match(process.env.OPENCODE_API_KEY, /^xcmax-placeholder-/, 'model receives only a useless placeholder');
assert.notEqual(process.env.OPENCODE_API_KEY, 'fixture-model-key');
assert.equal(process.env.DEVFLEET_DEVICE_TOKEN, undefined);
assert.equal(process.env.PATH, ${JSON.stringify(process.env.PATH)});
for (const name of ['BASH_ENV', 'ENV', 'LD_PRELOAD', 'NODE_OPTIONS', 'NODE_PATH']) assert.equal(process.env[name], undefined);
if (process.platform === 'linux') {
  const { spawnSync } = require('node:child_process');
  const status = fs.readFileSync('/proc/self/status', 'utf8');
  const field = name => status.match(new RegExp('^' + name + ':\\\\s*(\\\\S+)', 'm'))?.[1];
  for (const name of ['CapEff', 'CapPrm', 'CapAmb', 'CapInh']) assert.match(field(name), /^0+$/);
  assert.equal(field('NoNewPrivs'), '1');
  assert.equal(field('Seccomp'), '2');
  assert.equal(status.match(/^NSpid:[ \\t]*([^\\n]*)/m)?.[1].trim(), String(process.pid));
  assert.notEqual(fs.readlinkSync('/proc/self/ns/pid'), ${JSON.stringify(process.platform === 'linux' ? readlinkSync('/proc/self/ns/pid') : '')});
  assert.equal(fs.existsSync('/proc/${process.pid}'), false, 'host control process must not be visible');
  assert.throws(() => fs.openSync('/proc/1/mem', 'r+'), error => ['EACCES', 'EPERM'].includes(error.code));
  const nested = spawnSync('/usr/bin/unshare', ['--user', '--map-root-user', 'true'], { encoding: 'utf8' });
  assert.equal(nested.error, undefined);
  assert.notEqual(nested.status, 0);
  assert.match(nested.stderr, /Operation not permitted/);
  const socket = spawnSync(process.execPath, ['-e',
    'const s=require("node:net").createServer();s.on("error",e=>process.exit(e.code==="EPERM"?0:3));s.listen(process.env.TMPDIR+"/forbidden.sock",()=>process.exit(2));'],
    { encoding: 'utf8' });
  assert.equal(socket.error, undefined);
  assert.equal(socket.status, 0, socket.stderr);
}
assert.throws(() => fs.readFileSync(${JSON.stringify(protectedFile)}));
assert.throws(() => fs.writeFileSync('report-write.txt', 'unexpected'));
assert.equal(JSON.parse(process.env.OPENCODE_PERMISSION).bash, 'deny');
let client, finish;
const sessionID = 'ses_1';
function event(type, properties) {
  client.write('data:' + JSON.stringify({ type, properties: { sessionID, ...properties } }) + '\\n\\n');
}
const server = http.createServer(async (req, res) => {
  if (req.url === '/event') {
    client = res;
    res.writeHead(200, { 'content-type': 'text/event-stream' }).flushHeaders();
    return;
  }
  let raw = '';
  for await (const chunk of req) raw += chunk;
  res.setHeader('content-type', 'application/json');
  if (req.url === '/config') {
    const config = JSON.parse(process.env.OPENCODE_CONFIG_CONTENT);
    config.provider.xcmax.options.apiKey = process.env.OPENCODE_API_KEY;
    return res.end(JSON.stringify(config));
  }
  const body = JSON.parse(raw);
  if (req.url === '/session') {
    assert.deepEqual(body.permission, [
      { permission: '*', pattern: '*', action: 'deny' },
      ...['read', 'glob', 'grep', 'list'].map(permission => ({ permission, pattern: '*', action: 'allow' })),
    ]);
    return res.end(JSON.stringify({ id: sessionID }));
  }
  if (req.url.endsWith('/message')) {
    assert.equal(body.agent, 'plan');
    finish = res;
    event('permission.asked', { id: 'per_1' });
    return;
  }
  assert.equal(req.url, '/permission/per_1/reply');
  assert.equal(body.reply, 'reject');
  res.end('true');
  event('message.part.updated', { part: { id: 'part_1', type: 'text' } });
  event('message.part.delta', { field: 'text', partID: 'part_1', delta: 'READY' });
  setTimeout(() => finish.end(JSON.stringify({ parts: [{ type: 'text', text: 'READY' }] })), 200);
});
server.listen(0, '127.0.0.1', () => console.log('http://127.0.0.1:' + server.address().port));
`, { mode: 0o700 });
  const logs = [];
  const options = {
    executable,
    reportOnly: true,
    timeoutMs: 10000,
    log: text => logs.push(text),
    env: {
      PATH: process.env.PATH, DEVFLEET_OPENCODE_SANDBOX_ENTRY: sandbox,
      BASH_ENV: join(cwd, 'untrusted-init.sh'), ENV: join(cwd, 'untrusted-init.sh'),
      NODE_OPTIONS: '--require ./untrusted-init.cjs', NODE_PATH: cwd,
      DEVFLEET_DEVICE_TOKEN: 'fixture-token', OPENCODE_API_KEY: 'fixture-model-key',
      PARA_PLATFORM_GATEWAY_URL: 'https://example.invalid/v1', PARA_OPENCODE_MODEL: 'coding',
    },
  };
  writeFileSync(join(cwd, 'untrusted-init.sh'), 'exit 97\n');
  writeFileSync(join(cwd, 'untrusted-init.cjs'), 'throw new Error("untrusted startup hook executed");\n');
  assert.equal(await runOpenCodeAgent(cwd, 'Review the task', options), 'READY');
  assert.equal(await runOpenCodeAgent(cwd, 'Review without a log consumer', { ...options, log: undefined }), 'READY');
  assert.ok(logs.some(line => line.includes('已拒绝')));
  assert.ok(logs.some(line => line.includes('READY')));
  assert.equal(readFileSync(protectedFile, 'utf8'), 'untouched');
});
