import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  GRANT_PROMPT_KEY,
  REDACTED,
  createCredentialVault,
  parseCredentialGrant,
  redactSecrets,
} from './credential_vault.mjs';

const fresh = (prefix) => `${prefix}-${randomBytes(12).toString('hex')}`;
const tmp = () => mkdtempSync(path.join(tmpdir(), 'cred-vault-'));
const rows = (file) => readFileSync(file, 'utf8').trim().split('\n').map((l) => JSON.parse(l));

test('getCredential audits who/when/task/purpose and never the value', () => {
  const auditPath = path.join(tmp(), 'audit.jsonl');
  const value = fresh('v');
  const vault = createCredentialVault({ actor: 'unit', env: { XCMAX_UNIT_TOKEN: value }, auditPath });
  assert.equal(vault.getCredential('XCMAX_UNIT_TOKEN', { taskId: 't-1', purpose: 'unit' }), value);
  const raw = readFileSync(auditPath, 'utf8');
  assert.ok(!raw.includes(value));
  const row = rows(auditPath).at(-1);
  assert.equal(row.event, 'access');
  assert.equal(row.outcome, 'hit');
  assert.equal(row.actor, 'unit');
  assert.equal(row.task_id, 't-1');
  assert.equal(row.purpose, 'unit');
  assert.equal(row.backend, 'env');
  assert.ok(row.ts);
  assert.throws(() => vault.getCredential('XCMAX_UNIT_TOKEN', { taskId: '', purpose: 'unit' }));
});

test('fallback resolver is audited and file backend requires 0600', () => {
  const dir = tmp();
  const auditPath = path.join(dir, 'audit.jsonl');
  const value = fresh('f');
  const vault = createCredentialVault({ env: {}, auditPath });
  assert.equal(vault.getCredential('DEVFLEET_DEVICE_TOKEN', { taskId: 's', purpose: 'ws', fallback: () => value }), value);
  assert.equal(rows(auditPath).at(-1).backend, 'fallback');
  const secretDir = path.join(dir, 'secrets');
  const fileEnv = { XCMAX_CREDENTIAL_FILE_DIR: secretDir };
  assert.throws(() => createCredentialVault({ env: { XCMAX_CREDENTIAL_BACKENDS: 'vault' }, auditPath })
    .getCredential('XCMAX_ANY_TOKEN', { taskId: 't', purpose: 'p' }), /尚未实现/);
  if (process.platform !== 'win32') {
    mkdirSync(secretDir, { recursive: true });
    const file = path.join(secretDir, 'XCMAX_FILE_TOKEN');
    writeFileSync(file, `${value}\n`);
    chmodSync(file, 0o644);
    const fileVault = createCredentialVault({ env: fileEnv, auditPath });
    assert.throws(() => fileVault.getCredential('XCMAX_FILE_TOKEN', { taskId: 't', purpose: 'p' }), /0600/);
    chmodSync(file, 0o600);
    assert.equal(fileVault.getCredential('XCMAX_FILE_TOKEN', { taskId: 't', purpose: 'p' }), value);
  }
});

test('grant from prompt limits scope, expires, and is revoked at task end', () => {
  const auditPath = path.join(tmp(), 'audit.jsonl');
  let clock = 1_000_000_000_000;
  const value = fresh('g');
  const other = fresh('o');
  const env = { OPENAI_API_KEY: value, XCMAX_OTHER_TOKEN: other, XCMAX_CREDENTIAL_SCOPED_CHILD_ENV: '1', PATH: '/bin' };
  const vault = createCredentialVault({ env, auditPath, now: () => clock });
  const grantRef = { grant_id: 'cg_1', task_id: 'task-1', scopes: ['OPENAI_API_KEY'], issued_at: 0, expires_at: clock / 1000 + 60 };
  const prompt = `fix it\n${GRANT_PROMPT_KEY}=${JSON.stringify(grantRef)}`;
  const grant = parseCredentialGrant(prompt);
  assert.equal(grant.grant_id, 'cg_1');
  assert.ok(!prompt.includes(value));

  const child = vault.childEnv(env, grant, { tool: 'codex' });
  assert.equal(child.OPENAI_API_KEY, value);
  assert.equal(child.XCMAX_OTHER_TOKEN, undefined);
  assert.equal(child.PATH, '/bin');
  assert.throws(() => vault.getCredential('XCMAX_OTHER_TOKEN', { taskId: 'task-1', purpose: 'p', grant }), /out_of_scope/);

  clock += 61_000;
  assert.equal(vault.grantStatus(grant), 'expired');
  assert.equal(vault.childEnv(env, grant, { tool: 'codex' }).OPENAI_API_KEY, undefined);
  assert.throws(() => vault.getCredential('OPENAI_API_KEY', { taskId: 'task-1', purpose: 'p', grant }), /expired/);

  clock -= 61_000;
  vault.revokeTask('task-1');
  assert.equal(vault.grantStatus(grant), 'revoked');
  assert.ok(!readFileSync(auditPath, 'utf8').includes(value));
});

test('child env passes through unchanged unless scoped mode is enabled', () => {
  const auditPath = path.join(tmp(), 'audit.jsonl');
  const env = { XCMAX_OTHER_TOKEN: fresh('p'), PATH: '/bin' };
  const vault = createCredentialVault({ env, auditPath });
  assert.deepEqual(vault.childEnv(env, null, { tool: 'codex' }), env);
  assert.equal(rows(auditPath).at(-1).mode, 'passthrough');
});

test('redaction hides env secrets, loaded values and token shapes in reports', () => {
  const auditPath = path.join(tmp(), 'audit.jsonl');
  const envValue = fresh('e');
  const loaded = fresh('l');
  const vault = createCredentialVault({ env: { XCMAX_SAMPLE_PASSWORD: envValue }, auditPath,
    backends: [{ name: 'test', fetch: () => loaded }] });
  vault.getCredential('XCMAX_LOADED_TOKEN', { taskId: 't', purpose: 'p' });
  const out = vault.redact(`a ${envValue} b ${loaded} c Authorization: Bearer abc.def`);
  assert.ok(!out.includes(envValue) && !out.includes(loaded) && !out.includes('abc.def'));
  assert.ok(out.includes(REDACTED));
  const payload = vault.redactPayload({ type: 'task_log', content: `x ${loaded}`, nested: [{ e: envValue }], n: 3 });
  assert.ok(!JSON.stringify(payload).includes(loaded) && !JSON.stringify(payload).includes(envValue));
  assert.equal(payload.n, 3);
  assert.equal(redactSecrets('plain text', { env: {} }), 'plain text');
});
