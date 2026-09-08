import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, symlinkSync, statSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { provisionControl } from './provision_para_control.mjs';

test('cutover preserves devices and data, protects secrets, and refuses live API', async () => {
  assert.ok(process.env.PARA_TEST_PACKAGE_ROOT, 'Set PARA_TEST_PACKAGE_ROOT to the Para package checkout');
  const dependencyRoot = resolve(process.env.PARA_TEST_PACKAGE_ROOT);
  const require = createRequire(join(dependencyRoot, 'package.json'));
  const Database = require('better-sqlite3'), jwt = require('jsonwebtoken'), dotenv = require('dotenv');
  const root = mkdtempSync(join(tmpdir(), 'para-provision-test-'));
  const paraRoot = join(root, 'para'); mkdirSync(paraRoot);
  writeFileSync(join(paraRoot, 'package.json'), '{}');
  symlinkSync(join(dependencyRoot, 'node_modules'), join(paraRoot, 'node_modules'));
  writeFileSync(join(paraRoot, '.env'), 'KEEP_SETTING=preserved\nJWT_SECRET=previous-secret\n');
  const dbPath = join(root, 'fixture.db');
  const database = new Database(dbPath);
  database.exec(`CREATE TABLE users(id TEXT PRIMARY KEY,email TEXT UNIQUE,password_hash TEXT,is_guest INTEGER);
    CREATE TABLE devices(id TEXT PRIMARY KEY,user_id TEXT,device_token_hash TEXT);
    CREATE TABLE tasks(id TEXT PRIMARY KEY,user_id TEXT);
    CREATE TABLE sub_tasks(id TEXT PRIMARY KEY,task_id TEXT,status TEXT);
    INSERT INTO users VALUES('owner','guest@devfleet.local','',1);
    INSERT INTO devices VALUES('mac','owner','unchanged-device-hash');
    INSERT INTO tasks VALUES('historical','owner');
    INSERT INTO sub_tasks VALUES('old-sub','historical','completed');`);
  const config = { para_root: paraRoot, database_path: dbPath, state_dir: join(root, 'state'),
    owner_id: 'owner', device_ids: ['mac'], repo_url: 'https://github.com/42433422/XCMAX.git' };
  try {
    await provisionControl(config);
    assert.equal(database.prepare('SELECT is_guest FROM users').get().is_guest, 1);
    const credentialPath = join(config.state_dir, 'control-credentials.json');
    assert.equal(statSync(credentialPath).mode & 0o077, 0);
    const prepared = readFileSync(credentialPath, 'utf8');
    await provisionControl(config);
    assert.equal(readFileSync(credentialPath, 'utf8'), prepared);
    await assert.rejects(provisionControl({ ...config, apply: true }, async () => false), /stop_para_api/);
    const result = await provisionControl({ ...config, apply: true }, async () => true);
    assert.equal(result.applied, true);
    const credentials = JSON.parse(prepared);
    const owner = database.prepare('SELECT * FROM users').get();
    assert.equal(owner.id, 'owner'); assert.equal(owner.is_guest, 0);
    assert.equal(require('bcryptjs').compareSync(credentials.password, owner.password_hash), true);
    assert.equal(database.prepare('SELECT device_token_hash FROM devices').get().device_token_hash, 'unchanged-device-hash');
    assert.equal(database.prepare('SELECT COUNT(*) AS n FROM sub_tasks').get().n, 1);
    const environment = dotenv.parse(readFileSync(join(paraRoot, '.env')));
    assert.equal(environment.KEEP_SETTING, 'preserved');
    assert.equal(JSON.parse(environment.DEVFLEET_XCMAX_SERVICE_JSON).owner_id, 'owner');
    assert.equal(jwt.verify(credentials.legacy_admin_jwt, environment.JWT_SECRET).id, 'owner');
    assert.throws(() => jwt.verify(jwt.sign({ id: 'owner' }, 'previous-secret'), environment.JWT_SECRET));
  } finally { database.close(); rmSync(root, { recursive: true, force: true }); }
});
