import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { runOpenCodeAgent } from './opencode_agent.mjs';

const sandbox = process.env.PARA_TEST_SANDBOX_ENTRY;

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
  const body = JSON.parse(raw);
  res.setHeader('content-type', 'application/json');
  if (req.url === '/session') return res.end(JSON.stringify({ id: sessionID }));
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
  const result = await runOpenCodeAgent(cwd, 'Review the task', {
    executable,
    reportOnly: true,
    timeoutMs: 10000,
    log: text => logs.push(text),
    env: {
      PATH: process.env.PATH, DEVFLEET_OPENCODE_SANDBOX_ENTRY: sandbox,
      DEVFLEET_DEVICE_TOKEN: 'fixture-token', OPENCODE_API_KEY: 'fixture-model-key',
      PARA_PLATFORM_GATEWAY_URL: 'https://example.invalid/v1', PARA_OPENCODE_MODEL: 'coding',
    },
  });
  assert.equal(result, 'READY');
  assert.ok(logs.some(line => line.includes('已拒绝')));
  assert.ok(logs.some(line => line.includes('READY')));
  assert.equal(readFileSync(protectedFile, 'utf8'), 'untouched');
});
