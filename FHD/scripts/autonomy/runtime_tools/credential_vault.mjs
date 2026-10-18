/**
 * 凭据统一托管（Mac 执行端第一版）：统一读取 + 访问审计 + 任务短期授权 + 脱敏。
 * 审计只记 谁/何时/哪个任务/什么用途/哪个后端/结果，永远不记凭据值。
 * 后端：env、file（目录内一个凭据一个文件，权限须 0600）；vault/kms 只预留接口。
 */
import { appendFileSync, existsSync, mkdirSync, readFileSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';

export const GRANT_PROMPT_KEY = 'MODSTORE_CREDENTIAL_GRANT';
export const REDACTED = '[REDACTED]';
const NAME_RE = /^[A-Z][A-Z0-9_]{1,127}$/;
const SECRET_NAME_RE = /(PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY|CREDENTIAL)/i;
const NON_SECRET = new Set(['', '0', '1', 'true', 'false', 'yes', 'no', 'on', 'off', 'none', 'null']);
const KEY_VALUE_RE = /(bearer\s+|(?:api[_-]?key|password|passwd|token|secret|authorization)\s*[:=]\s*(?:bearer\s+)?)[^\s,;'"]+/gi;
const TOKEN_SHAPES_RE = /(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+)/g;

export function envBackend(env = process.env) {
  return { name: 'env', fetch: (name) => String(env[name] || '').trim() || null };
}

export function fileBackend(directory) {
  return {
    name: 'file',
    fetch(name) {
      const path = join(directory, name);
      if (!existsSync(path)) return null;
      if (process.platform !== 'win32' && (statSync(path).mode & 0o077)) {
        throw new Error(`凭据文件权限过宽（须 0600）：${name}`);
      }
      return readFileSync(path, 'utf8').trim() || null;
    },
  };
}

export function reservedBackend(name) {
  return { name, fetch() { throw new Error(`凭据后端 ${name} 尚未实现（预留接口）`); } };
}

export function defaultBackends(env = process.env) {
  const fileDir = String(env.XCMAX_CREDENTIAL_FILE_DIR || '').trim();
  const order = String(env.XCMAX_CREDENTIAL_BACKENDS || '').split(',').map((s) => s.trim().toLowerCase()).filter(Boolean);
  const names = order.length ? order : (fileDir ? ['file', 'env'] : ['env']);
  return names.map((name) => {
    if (name === 'env') return envBackend(env);
    if (name === 'file') {
      if (!fileDir) throw new Error('选用 file 后端但未配置 XCMAX_CREDENTIAL_FILE_DIR');
      return fileBackend(fileDir);
    }
    if (name === 'vault' || name === 'kms') return reservedBackend(name);
    throw new Error(`未知凭据后端：${name}`);
  });
}

export function parseCredentialGrant(text) {
  const line = String(text || '').split(/\r?\n/).reverse().find((l) => l.startsWith(`${GRANT_PROMPT_KEY}=`));
  if (!line) return null;
  try {
    const raw = JSON.parse(line.slice(GRANT_PROMPT_KEY.length + 1));
    if (!raw || typeof raw.grant_id !== 'string' || !Number.isFinite(raw.expires_at)) return null;
    return {
      grant_id: raw.grant_id,
      task_id: String(raw.task_id || ''),
      scopes: Array.isArray(raw.scopes) ? raw.scopes.filter((s) => NAME_RE.test(String(s))) : [],
      expires_at: Number(raw.expires_at),
    };
  } catch {
    return null;
  }
}

export function envSecretValues(env = process.env) {
  return Object.entries(env)
    .filter(([key, value]) => SECRET_NAME_RE.test(key) && String(value || '').trim().length >= 8
      && !NON_SECRET.has(String(value).trim().toLowerCase()))
    .map(([, value]) => String(value).trim());
}

export function redactSecrets(text, { env = process.env, extraValues = [] } = {}) {
  let out = String(text ?? '');
  if (!out) return out;
  const values = [...new Set([...extraValues, ...envSecretValues(env)])].filter((v) => v && v.length >= 6);
  values.sort((a, b) => b.length - a.length);
  for (const value of values) out = out.split(value).join(REDACTED);
  return out.replace(KEY_VALUE_RE, (_m, prefix) => `${prefix}${REDACTED}`).replace(TOKEN_SHAPES_RE, REDACTED);
}

export function redactPayloadStrings(value, options = {}, depth = 0) {
  if (typeof value === 'string') return redactSecrets(value, options);
  if (depth > 5 || value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map((item) => redactPayloadStrings(item, options, depth + 1));
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, redactPayloadStrings(v, options, depth + 1)]));
}

export function createCredentialVault({
  actor = 'para_e2e_agent',
  env = process.env,
  backends,
  auditPath = env.XCMAX_CREDENTIAL_AUDIT_LOG || join(homedir(), '.xcmax', 'credential-audit.jsonl'),
  now = () => Date.now(),
} = {}) {
  const known = new Set();
  const revoked = new Map();

  function audit(event, fields = {}) {
    const record = { ts: new Date(now()).toISOString(), event, actor, pid: process.pid };
    for (const [key, value] of Object.entries(fields)) {
      if (/value/i.test(key) || value === undefined || value === null) continue;
      record[key] = typeof value === 'string' ? value.slice(0, 300) : value;
    }
    try {
      mkdirSync(dirname(auditPath), { recursive: true });
      appendFileSync(auditPath, `${JSON.stringify(record)}\n`, { mode: 0o600 });
    } catch {
      // 审计落盘失败不影响执行，但绝不把值写到别处。
    }
    return record;
  }

  function grantStatus(grant) {
    if (!grant) return 'none';
    if (revoked.has(grant.task_id) || revoked.has(grant.grant_id)) return 'revoked';
    return now() >= grant.expires_at * 1000 ? 'expired' : 'active';
  }

  function getCredential(name, { taskId, purpose, aliases = [], grant = null, fallback = null, required = false } = {}) {
    if (!NAME_RE.test(name || '')) throw new Error('凭据名须为大写下划线变量名');
    if (!String(taskId || '').trim() || !String(purpose || '').trim()) {
      throw new Error('getCredential 需要 taskId 与 purpose 用于审计');
    }
    const base = { credential: name, task_id: taskId, purpose };
    if (grant) {
      const status = grantStatus(grant);
      const reason = status !== 'active' ? status : (grant.scopes.includes(name) ? '' : 'out_of_scope');
      if (reason) {
        audit('access', { ...base, outcome: 'denied', reason, grant_id: grant.grant_id });
        throw new Error(`任务授权不允许读取 ${name}：${reason}`);
      }
    }
    for (const candidate of [name, ...aliases]) {
      for (const backend of backends || defaultBackends(env)) {
        const value = backend.fetch(candidate);
        if (value) {
          if (value.length >= 6) known.add(value);
          audit('access', { ...base, outcome: 'hit', backend: backend.name, resolved: candidate, grant_id: grant?.grant_id });
          return value;
        }
      }
    }
    if (typeof fallback === 'function') {
      const value = fallback();
      if (value) {
        if (String(value).length >= 6) known.add(String(value));
        audit('access', { ...base, outcome: 'hit', backend: 'fallback' });
        return String(value);
      }
    }
    audit('access', { ...base, outcome: 'miss' });
    if (required) throw new Error(`凭据 ${name} 未配置`);
    return null;
  }

  /** 子进程环境：默认原样透传；XCMAX_CREDENTIAL_SCOPED_CHILD_ENV=1 时只保留授权作用域内的密钥变量。 */
  function childEnv(baseEnv, grant, { taskId = '', tool = '' } = {}) {
    const enforce = String(env.XCMAX_CREDENTIAL_SCOPED_CHILD_ENV || '') === '1';
    const status = grantStatus(grant);
    const allowed = new Set(status === 'active' ? grant.scopes : []);
    const stripped = [];
    const out = { ...baseEnv };
    if (enforce) {
      for (const key of Object.keys(out)) {
        if (SECRET_NAME_RE.test(key) && !allowed.has(key)) {
          delete out[key];
          stripped.push(key);
        }
      }
    }
    audit('child_env', {
      task_id: taskId || grant?.task_id || 'unknown', purpose: `tool:${tool || 'unknown'}`,
      mode: enforce ? 'scoped' : 'passthrough', grant_id: grant?.grant_id, grant_status: status,
      stripped_count: stripped.length,
    });
    return out;
  }

  function revokeTask(taskId, reason = 'task_finished') {
    const key = String(taskId || '').trim();
    if (!key) return;
    revoked.set(key, now());
    audit('grant_revoke', { task_id: key, reason });
  }

  return {
    audit,
    childEnv,
    getCredential,
    grantStatus,
    revokeTask,
    redact: (text) => redactSecrets(text, { env, extraValues: [...known] }),
    redactPayload: (payload) => redactPayloadStrings(payload, { env, extraValues: [...known] }),
  };
}
