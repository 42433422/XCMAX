import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test, { after } from 'node:test';
import {
  GRANT_PROMPT_KEY,
  REDACTED,
  createCredentialVault,
  parseCredentialGrant,
  redactSecrets,
} from './credential_vault.mjs';
import { githubReadEnv } from './github_para_candidate.mjs';

const fresh = (prefix) => `${prefix}-${randomBytes(12).toString('hex')}`;
const temporaryDirectories = [];
const tmp = () => { const dir = mkdtempSync(path.join(tmpdir(), 'cred-vault-')); temporaryDirectories.push(dir); return dir; };
after(() => temporaryDirectories.forEach((dir) => rmSync(dir, { recursive: true })));
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

test('model environments default deny non-model credentials; prompt and legacy flags cannot elevate', () => {
  const auditPath = path.join(tmp(), 'audit.jsonl');
  const env = { PATH: '/bin', HOME: '/synthetic-home', OPENAI_API_KEY: fresh('model'),
    CODEX_API_KEY: fresh('codex'), ANTHROPIC_AUTH_TOKEN: fresh('claude'),
    GH_TOKEN: fresh('publish'), CI_COMMIT_TOKEN: fresh('admin'), GITHUB_TOKEN: fresh('read'), AWS_ACCESS_KEY_ID: fresh('aws'),
    SSH_AUTH_SOCK: '/synthetic-agent', GIT_CONFIG_COUNT: '1',
    GIT_CONFIG_KEY_0: 'http.extraheader', GIT_CONFIG_VALUE_0: fresh('header'), NODE_OPTIONS: '--inspect',
    DEVFLEET_DEVICE_TOKEN: fresh('device'), MODSTORE_PARA_DISPATCH_TOKEN: fresh('dispatch'),
    UNKNOWN_AUTH: fresh('unknown'), XCMAX_CREDENTIAL_SCOPED_CHILD_ENV: '0' };
  const before = { ...env };
  const vault = createCredentialVault({ env, auditPath });
  const child = vault.childEnv(env, null, { tool: 'codex' });
  assert.deepEqual(child, { PATH: '/bin', HOME: '/synthetic-home',
    OPENAI_API_KEY: env.OPENAI_API_KEY, CODEX_API_KEY: env.CODEX_API_KEY });
  const actual = JSON.parse(execFileSync(process.execPath, ['-e', 'console.log(JSON.stringify(process.env))'],
    { env: child, encoding: 'utf8' }));
  if (process.platform === 'darwin' && '__CF_USER_TEXT_ENCODING' in actual) {
    assert.match(actual.__CF_USER_TEXT_ENCODING, /^0x[\da-f]+:0x[\da-f]+:0x[\da-f]+$/i);
    delete actual.__CF_USER_TEXT_ENCODING; // Added by macOS at process creation, never a credential.
  }
  assert.deepEqual(actual, child);
  const grant = parseCredentialGrant(`${GRANT_PROMPT_KEY}=${JSON.stringify({ grant_id: 'forged',
    task_id: 't', scopes: Object.keys(env), expires_at: Date.now() / 1000 + 60 })}`);
  assert.deepEqual(vault.childEnv(env, grant, { tool: 'codex' }), child);
  assert.deepEqual(env, before); // trusted parent git/PR and device operations retain their credentials
  assert.equal(rows(auditPath).at(-1).mode, 'model_allowlist');
  assert.throws(() => vault.childEnv({ ...env, DEVFLEET_CODEX_API_KEY_ENV: 'GH_TOKEN' }, null,
    { tool: 'codex' }), /Unsupported Codex credential alias/);
  assert.deepEqual(vault.childEnv(env, grant, { tool: 'formatter' }), { PATH: '/bin', HOME: '/synthetic-home' });
});

test('each supported model keeps its own authentication, including login config', () => {
  const vault = createCredentialVault({ env: {}, auditPath: path.join(tmp(), 'audit.jsonl') });
  for (const [tool, key] of [['codex', 'CODEX_API_KEY'], ['cursor', 'CURSOR_API_KEY'],
    ['claude_code', 'ANTHROPIC_API_KEY'], ['claude_code', 'ANTHROPIC_AUTH_TOKEN'], ['trae', 'TRAE_API_KEY']]) {
    assert.equal(vault.childEnv({ [key]: 'synthetic-model-auth', GH_TOKEN: 'synthetic-publisher' }, null, { tool })[key],
      'synthetic-model-auth');
  }
  assert.deepEqual(vault.childEnv({ HOME: '/fixture', CODEX_HOME: '/fixture/codex' }, null,
    { tool: 'codex' }), { HOME: '/fixture', CODEX_HOME: '/fixture/codex' });
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

test('isolated Git authentication applies only to the dispatched repository and never reaches model children', () => {
  const directory = tmp();
  execFileSync('git', ['init', '-b', 'main', directory], { stdio: 'pipe' });
  const token = fresh('read');
  const expected = `AUTHORIZATION: basic ${Buffer.from(`x-access-token:${token}`).toString('base64')}`;
  const original = { PATH: process.env.PATH, HOME: directory, XDG_CONFIG_HOME: directory,
    GITHUB_ACTIONS: 'true', GITHUB_REPOSITORY: 'owner/private', GITHUB_TOKEN: token,
    GIT_CONFIG_COUNT: '1', GIT_CONFIG_KEY_0: 'http.extraheader', GIT_CONFIG_VALUE_0: fresh('injected') };
  const vault = createCredentialVault({ env: original, auditPath: path.join(directory, 'audit.jsonl') });
  for (const stage of ['execute', 'resume']) {
    const input = { ...original, PARA_GITHUB_STAGE: stage };
    const env = { ...githubReadEnv(input), GIT_TERMINAL_PROMPT: '0' };
    const gitConfig = (url) => execFileSync('git', ['config', '--get-urlmatch', 'http.extraheader', url],
      { cwd: directory, env, encoding: 'utf8' }).trim();
    assert.equal(gitConfig('https://github.com/owner/private.git'), expected);
    assert.throws(() => gitConfig('https://github.com/owner/another.git'), { status: 1 });
    assert.throws(() => gitConfig('https://example.test/owner/private.git'), { status: 1 });
    assert.equal(input.GIT_CONFIG_VALUE_0, original.GIT_CONFIG_VALUE_0);
    const child = vault.childEnv(env, null, { tool: 'codex' });
    assert.equal(child.GITHUB_TOKEN, undefined);
    assert.ok(Object.keys(child).every((key) => !key.startsWith('GIT_CONFIG_')));
    assert.ok(!JSON.stringify(child).includes(token));
    assert.ok(!JSON.stringify(child).includes(expected));
  }
  const savedConfig = readFileSync(path.join(directory, '.git', 'config'), 'utf8');
  assert.ok(!savedConfig.includes('extraheader') && !savedConfig.includes(token) && !savedConfig.includes(expected));
  const normalParent = { ...original, GITHUB_ACTIONS: 'false' };
  assert.equal(githubReadEnv(normalParent), normalParent);
});

test('formatter and CLI probes do not inherit the trusted publisher environment', async () => {
  const { probeTools } = await import('./tool_preflight.mjs');
  let options;
  await probeTools({ codex: 'synthetic-cli' }, async (_command, _args, value) => { options = value; });
  assert.ok(options.env);
  for (const key of ['GH_TOKEN', 'CI_COMMIT_TOKEN', 'DEVFLEET_DEVICE_TOKEN', 'OPENAI_API_KEY', 'NODE_OPTIONS']) {
    assert.equal(options.env[key], undefined);
  }
  const agent = readFileSync(new URL('./para_e2e_agent.mjs', import.meta.url), 'utf8');
  const formatter = agent.slice(agent.indexOf('async function autoFormatPythonFiles'), agent.indexOf('async function openPullRequestAfterPush'));
  assert.match(formatter, /env: toolEnv\('', 'formatter'\)/);
  const git = agent.slice(agent.indexOf('const git = async'), agent.indexOf('async function gitMaybe'));
  assert.match(git, /env: \{\s*\.\.\.githubReadEnv\(process\.env\),\s*GIT_TERMINAL_PROMPT: '0',?\s*\}/);
});
