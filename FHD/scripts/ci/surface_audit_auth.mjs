/**
 * 表面巡检共用登录：
 * - P-W / P-App：默认 admin / admin123（account_kind=admin）
 * - P-S 企业版桌面：专用演示账号 xcagi-enterprise-demo（见 config/surface_audit_demo_account.json）
 */
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FHD_ROOT = path.resolve(__dirname, '../..')
const API_BASE = (process.env.SURFACE_AUDIT_API_URL || 'http://127.0.0.1:5000').replace(/\/$/, '')

function demoAccountDefaults() {
  const fallback = { username: 'xcagi-enterprise-demo', password: 'Demo@2026' }
  try {
    const raw = fs.readFileSync(path.join(FHD_ROOT, 'config/surface_audit_demo_account.json'), 'utf8')
    const cfg = JSON.parse(raw)
    return {
      username: String(cfg.username || fallback.username).trim(),
      password: String(cfg.password || fallback.password),
    }
  } catch {
    return fallback
  }
}

function parseCookies(setCookieHeaders) {
  const jar = {}
  const lines = Array.isArray(setCookieHeaders)
    ? setCookieHeaders
    : setCookieHeaders
      ? [setCookieHeaders]
      : []
  for (const line of lines) {
    const part = String(line).split(';')[0]
    const idx = part.indexOf('=')
    if (idx > 0) jar[part.slice(0, idx).trim()] = part.slice(idx + 1).trim()
  }
  return jar
}

async function fetchJson(url, opts = {}) {
  const res = await fetch(url, opts)
  const text = await res.text()
  let body = {}
  try {
    body = JSON.parse(text)
  } catch {
    body = { raw: text }
  }
  const setCookie = res.headers.getSetCookie ? res.headers.getSetCookie() : res.headers.get('set-cookie')
  return { status: res.status, body, cookies: parseCookies(setCookie) }
}

function resolveCredentials(accountKind = 'admin') {
  const kind = String(accountKind || 'admin').trim().toLowerCase()
  const demo = demoAccountDefaults()
  if (kind === 'enterprise') {
    const user =
      process.env.SURFACE_AUDIT_DEMO_USER ||
      process.env.SURFACE_AUDIT_ENTERPRISE_USER ||
      process.env.XCAGI_SURFACE_AUDIT_ENTERPRISE_USER ||
      process.env.SURFACE_AUDIT_USER ||
      demo.username
    const password =
      process.env.SURFACE_AUDIT_DEMO_PASSWORD ||
      process.env.SURFACE_AUDIT_ENTERPRISE_PASSWORD ||
      process.env.XCAGI_SURFACE_AUDIT_ENTERPRISE_PASSWORD ||
      process.env.SURFACE_AUDIT_PASSWORD ||
      demo.password
    if (user && password) return { username: user, password, accountKind: 'enterprise' }
  }
  return {
    username: process.env.SURFACE_AUDIT_USER || 'admin',
    password: process.env.SURFACE_AUDIT_PASSWORD || 'admin123',
    accountKind: kind === 'enterprise' ? 'admin' : kind || 'admin',
  }
}

async function authHeaders(auth, extra = {}) {
  return {
    Accept: 'application/json',
    ...(auth?.csrf_token ? { 'X-CSRF-Token': auth.csrf_token } : {}),
    ...(cookieHeader(auth) ? { Cookie: cookieHeader(auth) } : {}),
    ...extra,
  }
}

/** @returns {Promise<{session_id:string,csrf_token:string,access_token:string,refresh_token:string,market_access_token:string,market_refresh_token:string,username:string,user_id:number,cookies:object,account_kind?:string,market_is_admin?:boolean,market_is_enterprise?:boolean,impersonating?:boolean}>} */
export async function loginSurfaceAudit(options = {}) {
  const creds = resolveCredentials(options.accountKind || process.env.SURFACE_AUDIT_ACCOUNT_KIND || 'admin')
  const health = await fetchJson(`${API_BASE}/api/health`)
  const csrf = health.cookies.csrf_token || ''
  const web = await fetchJson(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      Cookie: Object.entries({ ...health.cookies, csrf_token: csrf })
        .filter(([, v]) => v)
        .map(([k, v]) => `${k}=${v}`)
        .join('; '),
    },
    body: JSON.stringify({
      username: creds.username,
      password: creds.password,
      account_kind: creds.accountKind,
    }),
  })
  if (!web.body.success && !web.body.ok) {
    throw new Error(web.body.message || web.body.error?.message || `登录失败 HTTP ${web.status}`)
  }
  const cookies = { ...health.cookies, ...web.cookies }
  const sessionId = web.body.session_id || cookies.session_id || ''
  let mobile = { body: { data: {} }, cookies: {} }
  try {
    mobile = await fetchJson(`${API_BASE}/api/mobile/v1/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': cookies.csrf_token || csrf,
        Cookie: Object.entries(cookies)
          .filter(([, v]) => v)
          .map(([k, v]) => `${k}=${v}`)
          .join('; '),
      },
      body: JSON.stringify({
        username: creds.username,
        password: creds.password,
        account_kind: creds.accountKind,
      }),
    })
  } catch {
    /* mobile 路由可选 */
  }
  const md = mobile.body.data || {}
  const auth = {
    session_id: md.session_id || sessionId,
    csrf_token: cookies.csrf_token || csrf,
    access_token: md.access_token || web.body.access_token || '',
    refresh_token: md.refresh_token || web.body.refresh_token || '',
    market_access_token: md.market_access_token || web.body.market_access_token || '',
    market_refresh_token: md.market_refresh_token || web.body.market_refresh_token || '',
    username: (web.body.user && web.body.user.username) || creds.username,
    user_id: (web.body.user && web.body.user.id) || 1,
    cookies,
    account_kind: web.body.account_kind || creds.accountKind,
    market_is_admin: Boolean(web.body.market_is_admin),
    market_is_enterprise: Boolean(web.body.market_is_enterprise),
    impersonating: false,
  }
  const me = await fetchSessionMe(auth)
  if (me) {
    auth.account_kind = me.account_kind || auth.account_kind
    auth.market_is_admin = Boolean(me.market_is_admin)
    auth.market_is_enterprise = Boolean(me.market_is_enterprise)
    auth.impersonating = me.impersonating_market_user_id != null
  }
  return auth
}

export async function fetchSessionMe(auth) {
  const res = await fetchJson(`${API_BASE}/api/auth/me`, {
    headers: await authHeaders(auth),
  })
  const data = res.body?.data
  return data && typeof data === 'object' ? data : null
}

async function pickEnterpriseMarketUser(auth) {
  const forced = String(process.env.SURFACE_AUDIT_IMPERSONATE_MARKET_USER_ID || '').trim()
  if (forced) {
    return { market_user_id: Number(forced), username: process.env.SURFACE_AUDIT_IMPERSONATE_USERNAME || '' }
  }
  const res = await fetchJson(`${API_BASE}/api/xcmax/admin/market/users`, {
    headers: await authHeaders(auth),
  })
  const rows = Array.isArray(res.body?.data)
    ? res.body.data
    : Array.isArray(res.body?.users)
      ? res.body.users
      : []
  for (const row of rows) {
    if (!row || typeof row !== 'object') continue
    const isAdmin = Boolean(row.is_admin ?? row.is_market_admin)
    const isEnterprise = Boolean(row.is_enterprise ?? row.enterprise)
    if (isAdmin) continue
    const id = row.id ?? row.user_id ?? row.market_user_id
    if (id == null) continue
    if (isEnterprise || rows.length === 1) {
      return {
        market_user_id: Number(id),
        username: String(row.username || row.name || '').trim(),
        company: String(row.company || row.company_brand || '').trim(),
      }
    }
  }
  for (const row of rows) {
    if (!row || typeof row !== 'object') continue
    if (Boolean(row.is_admin ?? row.is_market_admin)) continue
    const id = row.id ?? row.user_id ?? row.market_user_id
    if (id == null) continue
    return {
      market_user_id: Number(id),
      username: String(row.username || row.name || '').trim(),
      company: String(row.company || row.company_brand || '').trim(),
    }
  }
  return null
}

async function impersonateEnterpriseUser(auth, target) {
  const res = await fetchJson(`${API_BASE}/api/xcmax/admin/impersonate`, {
    method: 'POST',
    headers: await authHeaders(auth, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      market_user_id: target.market_user_id,
      username: target.username || '',
      company: target.company || '',
    }),
  })
  if (!res.body?.success) {
    throw new Error(res.body?.message || '管理员代管企业用户失败')
  }
  auth.impersonating = true
  auth.impersonating_market_user_id = target.market_user_id
  auth.impersonating_username = target.username || ''
  const me = await fetchSessionMe(auth)
  if (me) {
    auth.account_kind = me.account_kind || auth.account_kind
    auth.market_is_admin = Boolean(me.market_is_admin)
    auth.market_is_enterprise = Boolean(me.market_is_enterprise)
    auth.impersonating = me.impersonating_market_user_id != null
  }
  return auth
}

/** P-S / P-App 企业版：演示企业账号登录；P-S 禁止回退 admin（会截到 Mod 后台） */
export async function loginSurfaceAuditForLane(lane) {
  const laneKey = String(lane || '').trim()
  if (laneKey !== 'P-S' && laneKey !== 'P-App') {
    return loginSurfaceAudit({ accountKind: process.env.SURFACE_AUDIT_ACCOUNT_KIND || 'admin' })
  }

  const auth = await loginSurfaceAudit({ accountKind: 'enterprise' })
  if (auth.market_is_admin && !auth.impersonating) {
    throw new Error(
      `${laneKey} 演示账号仍被识别为管理员：请确认已写入 xcagi-enterprise-demo，并使用 account_kind=enterprise 登录`,
    )
  }
  return auth
}

/** Playwright cookie 列表（127.0.0.1） */
export function playwrightCookies(auth, host = '127.0.0.1') {
  const rows = []
  if (auth.session_id) {
    rows.push({ name: 'session_id', value: auth.session_id, domain: host, path: '/' })
  }
  if (auth.csrf_token) {
    rows.push({ name: 'csrf_token', value: auth.csrf_token, domain: host, path: '/' })
  }
  return rows
}

function cookieHeader(auth) {
  const parts = []
  if (auth.session_id) parts.push(`session_id=${auth.session_id}`)
  if (auth.csrf_token) parts.push(`csrf_token=${auth.csrf_token}`)
  if (auth.cookies && typeof auth.cookies === 'object') {
    for (const [k, v] of Object.entries(auth.cookies)) {
      if (v && !parts.some((p) => p.startsWith(`${k}=`))) parts.push(`${k}=${v}`)
    }
  }
  return parts.join('; ')
}

/** 从 FHD / MODstore 同源接口拉取管理端身份校验码（6 位 HEX）。 */
export async function fetchDigestIdentity(auth, apiBase) {
  const base = (apiBase || API_BASE).replace(/\/$/, '')
  const res = await fetchJson(`${base}/api/xcmax/admin/digest-identity`, {
    headers: {
      Accept: 'application/json',
      ...(auth.csrf_token ? { 'X-CSRF-Token': auth.csrf_token } : {}),
      ...(cookieHeader(auth) ? { Cookie: cookieHeader(auth) } : {}),
    },
  })
  const data = res.body?.data && typeof res.body.data === 'object' ? res.body.data : {}
  let code = String(data.code || '').trim().toUpperCase()
  let digest_api_base = String(data.digest_api_base || '').trim()
  if (code.length === 6 && /^[0-9A-F]{6}$/.test(code)) {
    return { code, digest_api_base: digest_api_base || base }
  }
  const isPublicHost =
    /^https:\/\//i.test(base) && !/127\.0\.0\.1|localhost/i.test(base)
  if (isPublicHost || process.env.SURFACE_AUDIT_STRICT_DIGEST === '1') {
    return { code: '', digest_api_base: digest_api_base || base }
  }
  if (res.body?.missing_route || !code) {
    code = localDigestIdentityCode()
    digest_api_base = digest_api_base || base
  }
  return { code, digest_api_base }
}

function localDigestIdentityCode(day) {
  const d = day || new Date().toISOString().slice(0, 10)
  const secret = process.env.XCMAX_DIGEST_IDENTITY_SECRET || 'xcmax-local-digest-dev'
  return createHash('sha256').update(`${secret}:${d}`).digest('hex').slice(0, 6).toUpperCase()
}

/** 提交身份校验码解锁管理端（与修茈市场 verify-admin-digest-code 同源）。 */
export async function verifyAdminDigestCode(auth, code, apiBase) {
  const c = String(code || '').trim().toUpperCase()
  if (!c) return false
  const base = (apiBase || API_BASE).replace(/\/$/, '')
  const res = await fetchJson(`${base}/api/auth/verify-admin-digest-code`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(auth.csrf_token ? { 'X-CSRF-Token': auth.csrf_token } : {}),
      ...(cookieHeader(auth) ? { Cookie: cookieHeader(auth) } : {}),
    },
    body: JSON.stringify({ code: c }),
  })
  return res.body?.success === true || res.body?.ok === true
}

/** curl 版（无 fetch 环境备用） */
export function loginSurfaceAuditSync() {
  const creds = resolveCredentials(process.env.SURFACE_AUDIT_ACCOUNT_KIND || 'admin')
  const py = `import json,urllib.request
api=${JSON.stringify(API_BASE)}
user=${JSON.stringify(creds.username)}
password=${JSON.stringify(creds.password)}
kind=${JSON.stringify(creds.accountKind)}
jar={}
def req(url, data=None, headers=None):
  h=dict(headers or {})
  if data is not None:
    import json as j
    data=j.dumps(data).encode()
    h.setdefault('Content-Type','application/json')
  r=urllib.request.Request(url,data=data,headers=h,method='POST' if data else 'GET')
  with urllib.request.urlopen(r,timeout=30) as resp:
    body=json.loads(resp.read().decode())
    for k,v in resp.headers.items():
      if k.lower()=='set-cookie' and '=' in v:
        jar[v.split('=')[0]]=v.split('=')[1].split(';')[0]
    return body
req(api+'/api/health')
csrf=jar.get('csrf_token','')
web=req(api+'/api/auth/login',{'username':user,'password':password,'account_kind':kind},{'X-CSRF-Token':csrf,'Cookie':';'.join(f'{k}={v}' for k,v in jar.items())})
if not web.get('success'): raise SystemExit(web.get('message') or 'login failed')
print(json.dumps({'session_id':web.get('session_id'),'csrf_token':csrf,'market_access_token':web.get('market_access_token',''),'market_refresh_token':web.get('market_refresh_token',''),'username':(web.get('user') or {}).get('username',user),'user_id':(web.get('user') or {}).get('id',1)}))`
  const out = execFileSync('python3', ['-c', py], { encoding: 'utf8' })
  return JSON.parse(out.trim())
}
