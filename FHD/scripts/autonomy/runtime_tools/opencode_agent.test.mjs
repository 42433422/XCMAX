import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { once } from 'node:events';
import { closeSync, mkdirSync, mkdtempSync, openSync, readFileSync, readlinkSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import test from 'node:test';
import { assertLinuxWorkloadIsolation, isOpenCodeReady, openCodeSandboxEntry, privateUserNamespaceArgs, privateUserNamespaceLauncher, runOpenCodeAgent } from './opencode_agent.mjs';

const sandbox = process.env.PARA_TEST_SANDBOX_ENTRY;

test('private namespace initialization requires the fixed SRT isolation flags and a non-root caller', () => {
  const options = { restricted: true, uid: 1000, euid: 1000 };
  const flags = ['--die-with-parent', '--unshare-user', '--unshare-pid', '--unshare-net', '--cap-drop', 'ALL', '--proc', '/proc'];
  const args = [...flags, '--', '/usr/bin/bash', '-c', 'fixed-vendor-command'];
  assert.deepEqual(privateUserNamespaceArgs(args, options), [...flags, '--cap-add', 'CAP_SYS_ADMIN', ...args.slice(flags.length)]);
  assert.deepEqual(privateUserNamespaceArgs(args, { ...options, restricted: false }), args);
  assert.deepEqual(privateUserNamespaceArgs(['--version'], options), ['--version']);
  for (const invalid of [
    { ...options, uid: 0, euid: 0 }, { ...options, euid: 0 }, { ...options, uid: undefined },
  ]) assert.throws(() => privateUserNamespaceArgs(args, invalid), /private_user_namespace_required/);
  for (const invalid of [
    args.filter(arg => arg !== '--unshare-user'), args.filter(arg => arg !== '--unshare-pid'),
    args.filter(arg => arg !== '--unshare-net'), args.filter(arg => arg !== '--die-with-parent'),
    args.filter(arg => arg !== '--cap-drop'), args.filter(arg => arg !== '--proc'),
    ['--', ...args], [...flags, '--uid', '0', '--', 'command'],
    [...flags, '--cap-add', 'ALL', '--', 'command'],
  ]) assert.throws(() => privateUserNamespaceArgs(invalid, options), /private_user_namespace_required/);
  assert.deepEqual(privateUserNamespaceArgs([...flags, '--args', '9', '--', 'command'], options),
    [...flags, '--args', '9', '--cap-add', 'CAP_SYS_ADMIN', '--', 'command']);
  for (const profile of [['--args', '8'], ['--args', '9', '--args', '9']]) {
    assert.throws(() => privateUserNamespaceArgs([...flags, ...profile, '--', 'command'], options), /unexpected_bwrap_profile_fd/);
  }
});

test('workloads reject ambient capabilities or outer procfs and require NNP and seccomp', () => {
  const status = 'CapEff:\t00000000\nCapPrm:\t00000000\nCapAmb:\t00000000\nCapInh:\t00200000\nNoNewPrivs:\t1\nSeccomp:\t2\nNSpid:\t42\n';
  assert.doesNotThrow(() => assertLinuxWorkloadIsolation(status));
  for (const name of ['CapEff', 'CapPrm', 'CapAmb']) {
    assert.throws(() => assertLinuxWorkloadIsolation(status.replace(name + ':\t00000000', name + ':\t00200000')), /isolation_required/);
  }
  for (const [before, after] of [['NoNewPrivs:\t1', 'NoNewPrivs:\t0'], ['Seccomp:\t2', 'Seccomp:\t0'], ['CapInh:\t00200000', 'CapInh:\t00200001'],
    ['NSpid:\t42', 'NSpid:\t12\t42'], ['NSpid:\t42', '']]) {
    assert.throws(() => assertLinuxWorkloadIsolation(status.replace(before, after)), /isolation_required/);
  }
});

test('native exec preserves the mount profile and argv, and cancellation reaches the final process', {
  skip: process.platform !== 'linux', timeout: 10000,
}, async t => {
  const root = mkdtempSync(join(tmpdir(), 'para-bwrap-fd-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const profile = join(root, 'profile');
  writeFileSync(profile, 'opaque-native-mount-profile\0');
  const validator = join(root, "validator with 'quotes'");
  writeFileSync(validator, '#!/bin/sh\nexit 42\n', { mode: 0o700 });
  const native = join(root, "native with 'quotes'");
  writeFileSync(native, `#!${process.execPath}
const fs = require('node:fs');
console.log(JSON.stringify({ pid: process.pid, ppid: process.ppid, args: process.argv.slice(2), profile: fs.readFileSync(9, 'utf8') }));
setInterval(() => {}, 1000);
`, { mode: 0o700 });
  const launcher = join(root, 'launcher');
  writeFileSync(launcher, privateUserNamespaceLauncher(validator, native), { mode: 0o700 });
  const flags = ['--unshare-user', '--unshare-pid', '--unshare-net', '--die-with-parent', '--cap-drop', 'ALL', '--proc', '/proc', '--args', '9'];
  const command = ['--', "literal 'quotes' \"$HOME\" $(false) ;\nsecond line", '--args', '8', '--cap-add', 'ALL'];
  const fd = openSync(profile, 'r');
  try {
    const child = spawn(launcher, [...flags, ...command], {
      env: { PATH: '/usr/bin:/bin' }, stdio: ['ignore', 'pipe', 'pipe', ...Array(6).fill('ignore'), fd],
    });
    t.after(() => child.kill('SIGKILL'));
    const lines = createInterface({ input: child.stdout });
    child.on('error', error => lines.emit('error', error));
    const [line] = await once(lines, 'line');
    const result = JSON.parse(line);
    assert.equal(result.pid, child.pid, 'no intermediate supervisor may survive cancellation');
    assert.equal(result.ppid, process.pid);
    assert.equal(result.profile, 'opaque-native-mount-profile\0');
    assert.deepEqual(result.args, [...flags, '--cap-add', 'CAP_SYS_ADMIN', ...command]);
    const stopped = once(child, 'exit');
    assert.equal(child.kill('SIGTERM'), true);
    assert.deepEqual(await stopped, [null, 'SIGTERM']);
  } finally { closeSync(fd); }
});

test('the native launcher only accepts successful validation or the explicit namespace decision', {
  skip: process.platform !== 'linux',
}, t => {
  const root = mkdtempSync(join(tmpdir(), 'para-bwrap-check-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const validator = join(root, 'validator'), native = join(root, 'native'), launcher = join(root, 'launcher');
  writeFileSync(native, '#!/bin/sh\nprintf "%s\\n" "$@"\n', { mode: 0o700 });
  writeFileSync(launcher, privateUserNamespaceLauncher(validator, native), { mode: 0o700 });
  for (const [body, status] of [['exit 1', 1], ['exit 2', 2], ['kill -TERM $$', 143]]) {
    writeFileSync(validator, '#!/bin/sh\n' + body + '\n', { mode: 0o700 });
    assert.throws(() => execFileSync(launcher, ['--version'], { env: { PATH: '/usr/bin:/bin' }, stdio: 'pipe' }), error => {
      assert.equal(error.status, status);
      assert.equal(error.stdout.length, 0, 'failed validation must not reach the native command');
      return true;
    });
  }
  writeFileSync(validator, '#!/bin/sh\nexit 0\n', { mode: 0o700 });
  assert.equal(execFileSync(launcher, ['--version'], { env: { PATH: '/usr/bin:/bin' }, encoding: 'utf8' }), '--version\n');
});

test('unavailable sandbox or gateway cannot advertise OpenCode or start a task', async () => {
  const env = { DEVFLEET_OPENCODE_AGENT: process.execPath,
    DEVFLEET_OPENCODE_SANDBOX_ENTRY: join(tmpdir(), 'missing-para-sandbox', 'cli.js') };
  assert.equal(isOpenCodeReady(env), false);
  assert.equal(openCodeSandboxEntry(env), undefined);
  await assert.rejects(runOpenCodeAgent(tmpdir(), 'Must not execute', {
    env, timeoutMs: 1000, reportOnly: true,
  }), /Linux\/macOS.*沙箱/);
  if (sandbox) assert.equal(isOpenCodeReady({ ...env, DEVFLEET_OPENCODE_SANDBOX_ENTRY: sandbox }), false);
});

test('isolated OpenCode rejects interactive approval and finishes a report-only session', {
  skip: !sandbox || process.platform === 'win32',
}, async t => {
  const root = mkdtempSync(join(realpathSync(tmpdir()), 'para-opencode-contract-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const cwd = join(root, 'workspace');
  mkdirSync(cwd);
  const protectedFile = join(root, 'outside.txt');
  writeFileSync(protectedFile, 'untouched');
  const executable = join(root, 'fake-opencode');
  writeFileSync(executable, `#!${process.execPath}
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
assert.equal(process.env.DEVFLEET_DEVICE_TOKEN, undefined);
assert.equal(process.env.PATH, ${JSON.stringify(process.env.PATH)});
for (const name of ['BASH_ENV', 'ENV', 'LD_PRELOAD', 'NODE_OPTIONS', 'NODE_PATH']) assert.equal(process.env[name], undefined);
if (process.platform === 'linux') {
  const { spawnSync } = require('node:child_process');
  const status = fs.readFileSync('/proc/self/status', 'utf8');
  const field = name => status.match(new RegExp('^' + name + ':\\\\s*(\\\\S+)', 'm'))?.[1];
  for (const name of ['CapEff', 'CapPrm', 'CapAmb']) assert.match(field(name), /^0+$/);
  assert.equal(field('NoNewPrivs'), '1');
  assert.equal(field('Seccomp'), '2');
  assert.equal(status.match(/^NSpid:[ \\t]*([^\\n]*)/m)?.[1].trim(), String(process.pid));
  assert.notEqual(fs.readlinkSync('/proc/self/ns/pid'), ${JSON.stringify(process.platform === 'linux' ? readlinkSync('/proc/self/ns/pid') : '')});
  assert.equal(fs.existsSync('/proc/${process.pid}'), false, 'host control process must not be visible');
  assert.equal(BigInt('0x' + field('CapInh')) & ~(1n << 21n), 0n);
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
