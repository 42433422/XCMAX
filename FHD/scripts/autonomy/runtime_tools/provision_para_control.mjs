/** One-time, local cutover preparation. Secrets are written only to owner-readable files. */
import { randomBytes, createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync, renameSync, existsSync, statSync, chmodSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const secret = () => randomBytes(48).toString('base64url');
function privateWrite(path, value) {
  const temporary = `${path}.${randomBytes(8).toString('hex')}.pending`;
  writeFileSync(temporary, value, { flag: 'wx', mode: 0o600, flush: true });
  renameSync(temporary, path);
}
async function apiStopped() {
  try { return !execFileSync('/usr/sbin/lsof', ['-tiTCP:3001', '-sTCP:LISTEN'], { encoding: 'utf8' }).trim(); }
  catch (error) { return error.status === 1 && !String(error.stdout || '').trim(); }
}
export async function provisionControl(options, stopped = apiStopped) {
  const paraRoot = resolve(options.para_root), stateDir = resolve(options.state_dir);
  if (!Array.isArray(options.device_ids) || options.device_ids.length < 1
    || !/^https:\/\/github\.com\/42433422\/XCMAX(?:\.git)?$/.test(options.repo_url)) throw new Error('invalid_project_scope');
  const require = createRequire(join(paraRoot, 'package.json'));
  const Database = require('better-sqlite3'), bcrypt = require('bcryptjs'), jwt = require('jsonwebtoken');
  const databasePath = resolve(options.database_path || join(paraRoot, 'api/data/devfleet.db'));
  mkdirSync(stateDir, { recursive: true, mode: 0o700 });
  if ((statSync(stateDir).mode & 0o077) !== 0) throw new Error('state_directory_must_be_private');
  const database = new Database(databasePath, { fileMustExist: true, readonly: !options.apply });
  const secretsPath = join(stateDir, 'control-credentials.json');
  const envPath = join(paraRoot, '.env');
  try {
    const owner = database.prepare('SELECT * FROM users WHERE id=?').get(options.owner_id);
    if (!owner) throw new Error('owner_missing');
    for (const id of options.device_ids) {
      if (database.prepare('SELECT user_id FROM devices WHERE id=?').get(id)?.user_id !== owner.id) throw new Error('device_owner_mismatch');
    }
    if (database.prepare(`SELECT COUNT(*) AS n FROM sub_tasks s JOIN tasks t ON t.id=s.task_id
      WHERE t.user_id=? AND s.status IN ('running','pending')`).get(owner.id).n) throw new Error('active_work_must_drain_first');
    let credentials;
    if (existsSync(secretsPath)) {
      if (statSync(secretsPath).mode & 0o077) throw new Error('credentials_must_be_private');
      credentials = JSON.parse(readFileSync(secretsPath, 'utf8'));
      if (credentials.owner_id !== owner.id || JSON.stringify(credentials.device_ids) !== JSON.stringify(options.device_ids)
        || credentials.repo_url !== options.repo_url) throw new Error('prepared_scope_mismatch');
    } else {
      if (options.apply) throw new Error('prepare_required_before_apply');
      if (!owner.is_guest || !/^guest(?:_[^@]+)?@devfleet\.local$/.test(owner.email)) throw new Error('only_legacy_guest_owner_can_be_enrolled');
      if (existsSync(join(stateDir, 'before-control.db')) || existsSync(join(stateDir, 'before-control.env'))) {
        throw new Error('incomplete_preparation_preserved_use_new_state_directory');
      }
      await database.backup(join(stateDir, 'before-control.db'));
      chmodSync(join(stateDir, 'before-control.db'), 0o600);
      const oldEnv = existsSync(envPath) ? readFileSync(envPath, 'utf8') : '';
      privateWrite(join(stateDir, 'before-control.env'), oldEnv);
      const email = 'xcmax-controller@devfleet.local';
      const existing = database.prepare('SELECT id FROM users WHERE email=?').get(email);
      if (existing && existing.id !== owner.id) throw new Error('managed_email_already_owned');
      credentials = { owner_id: owner.id, device_ids: options.device_ids, repo_url: options.repo_url,
        email, password: secret(), jwt_secret: secret(), service_token: secret(),
        receipt_tokens: Object.fromEntries(options.device_ids.map(id => [id, secret()])),
        previous_email: owner.email, previous_is_guest: owner.is_guest };
      credentials.legacy_admin_jwt = jwt.sign({ id: owner.id, sub: owner.id, email }, credentials.jwt_secret, { expiresIn: '7d' });
      privateWrite(secretsPath, JSON.stringify(credentials, null, 2) + '\n');
    }
    if (!options.apply) return { prepared: true, state_dir: stateDir, device_count: options.device_ids.length };
    if (!await stopped()) throw new Error('stop_para_api_before_cutover');
    if (owner.email !== credentials.previous_email && owner.email !== credentials.email) throw new Error('owner_changed_since_prepare');
    const oldEnv = existsSync(envPath) ? readFileSync(envPath, 'utf8') : '';
    const grant = { owner_id: owner.id, device_ids: credentials.device_ids, repo_url: credentials.repo_url,
      token_sha256: createHash('sha256').update(credentials.service_token).digest('hex') };
    const appended = `\n# XCMAX managed control\nNODE_ENV=production\nJWT_SECRET=${credentials.jwt_secret}\nDEVFLEET_XCMAX_SERVICE_JSON='${JSON.stringify(grant)}'\n`;
    try {
      database.transaction(() => {
        database.prepare('UPDATE users SET email=?,password_hash=?,is_guest=0 WHERE id=?')
          .run(credentials.email, bcrypt.hashSync(credentials.password, 12), owner.id);
        privateWrite(envPath, oldEnv + appended);
      })();
    } catch (error) { privateWrite(envPath, oldEnv); throw error; }
    privateWrite(join(stateDir, 'cutover.json'), JSON.stringify({ owner_id: owner.id,
      device_count: options.device_ids.length, applied_at: new Date().toISOString(), device_identity_preserved: true }) + '\n');
    return { applied: true, state_dir: stateDir, device_count: options.device_ids.length };
  } finally { database.close(); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const configPath = process.argv[2];
  if (!configPath) throw new Error('Pass an owner-readable JSON configuration path');
  provisionControl(JSON.parse(readFileSync(configPath, 'utf8')))
    .then(result => process.stdout.write(JSON.stringify(result) + '\n'))
    .catch(error => { process.stderr.write(error.message + '\n'); process.exitCode = 1; });
}
