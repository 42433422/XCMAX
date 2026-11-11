import assert from 'node:assert/strict'
import { randomBytes } from 'node:crypto'
import fs from 'node:fs'
import { test } from 'node:test'
import { loginSurfaceAudit, resolveCredentials } from './surface_audit_auth.mjs'

test('audit credentials are explicit and missing enterprise auth never becomes admin', async () => {
  const keys = Object.keys(process.env).filter(k => /^(SURFACE_AUDIT|XCAGI_SURFACE_AUDIT)_.*(USER|PASSWORD)$/.test(k))
  const saved = Object.fromEntries(keys.map(k => [k, process.env[k]]))
  keys.forEach(k => delete process.env[k])
  const fetch = globalThis.fetch
  globalThis.fetch = () => { throw new Error('Unexpected network request') }
  try {
    for (const accountKind of ['enterprise', 'admin']) {
      assert.throws(() => resolveCredentials(accountKind), /credentials are required/)
      await assert.rejects(loginSurfaceAudit({ accountKind }), /credentials are required/)
    }
    const password = randomBytes(32).toString('hex')
    for (const key of ['SURFACE_AUDIT_DEMO_PASSWORD', 'SURFACE_AUDIT_ENTERPRISE_PASSWORD', 'XCAGI_SURFACE_AUDIT_ENTERPRISE_PASSWORD', 'SURFACE_AUDIT_PASSWORD']) {
      process.env[key] = password
      assert.deepEqual(resolveCredentials('enterprise'), { username: 'xcagi-enterprise-demo', password, accountKind: 'enterprise' })
      delete process.env[key]
    }
    process.env.SURFACE_AUDIT_USER = 'isolated-audit'
    process.env.SURFACE_AUDIT_PASSWORD = password
    assert.deepEqual(resolveCredentials('admin'), { username: 'isolated-audit', password, accountKind: 'admin' })
  } finally {
    for (const k of Object.keys(process.env)) if (/^(SURFACE_AUDIT|XCAGI_SURFACE_AUDIT)_.*(USER|PASSWORD)$/.test(k)) delete process.env[k]
    Object.assign(process.env, saved)
    globalThis.fetch = fetch
  }
})

test('login hints give guidance without interpolated credentials', () => {
  for (const locale of ['en-US', 'zh-CN']) {
    const text = JSON.parse(fs.readFileSync(new URL(`../../frontend/src/i18n/locales/${locale}/login.json`, import.meta.url), 'utf8')).login.devHint
    assert.ok(text.length > 20)
    assert.doesNotMatch(text, /\{'|xcagi-enterprise-demo|admin123/)
  }
})

test('development and audit runners do not select production by default', () => {
  const dev = fs.readFileSync(new URL('../dev/start-enterprise-dev.sh', import.meta.url), 'utf8')
  assert.doesNotMatch(dev, /XCAGI_USE_REMOTE_MARKET:-1|https:\/\/xiu-ci\.com/)
  assert.match(dev, /XCAGI_MARKET_BASE_URL:\?Remote market requires an explicit URL/)
  const runner = fs.readFileSync(new URL('./run_surface_audit.mjs', import.meta.url), 'utf8')
  assert.doesNotMatch(runner, /process\.env\.SURFACE_AUDIT_PASSWORD\s*=/)
  assert.match(runner, /'http:\/\/127\.0\.0\.1:5176'/)
})
