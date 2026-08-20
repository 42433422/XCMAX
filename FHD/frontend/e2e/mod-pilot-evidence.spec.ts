/**
 * Mod 商家试点四图 · 真实 UI 流程（禁止脚本伪造入账）
 * 前置: bash FHD/scripts/dev/capture_mod_pilot_evidence.sh
 *
 * 环境变量:
 *   MOD_PILOT_ADMIN_USER/PASSWORD  — 管理后台 catalog（默认 testuser）
 *   MOD_PILOT_MERCHANT_USER/PASSWORD — 企业商家（默认 modpilot）
 *   MOD_PILOT_ALIPAY_BUYER / MOD_PILOT_ALIPAY_BUYER_PASS — 支付宝沙箱买家（可选，用于自动付 0.01）
 */
import { test, expect } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const EVIDENCE = path.resolve(__dirname, '../../docs/evidence/mod')
const MARKET = process.env.MOD_PILOT_MARKET_URL || 'http://127.0.0.1:5176'
/** API 根（本地 Vite 代理用 MARKET；官网用 https://xiu-ci.com） */
const MARKET_API = process.env.MOD_PILOT_MARKET_API || MARKET
const FHD_WEB = process.env.MOD_PILOT_FHD_URL || 'http://127.0.0.1:5001'
/** 企业登录直打 API，避免 Vite 冷启动时误判 405/403 */
const FHD_API = process.env.MOD_PILOT_FHD_API || 'http://127.0.0.1:5000'
const ADMIN_USER = process.env.MOD_PILOT_ADMIN_USER || process.env.MOD_PILOT_USER || 'testuser'
const ADMIN_PASS = process.env.MOD_PILOT_ADMIN_PASSWORD || process.env.MOD_PILOT_PASSWORD || 'ModPilot2026!'
const MERCHANT_USER = process.env.MOD_PILOT_MERCHANT_USER || 'modpilot'
const MERCHANT_PASS = process.env.MOD_PILOT_MERCHANT_PASSWORD || 'ModPilot2026!'

/** 从 ~/.xcmax/mod-pilot.env 注入买家等密钥（不入库） */
function loadPilotEnvFile(): void {
  const candidates = [
    process.env.MOD_PILOT_ENV_FILE,
    path.join(process.env.HOME || '', '.xcmax/mod-pilot.env'),
    path.resolve(__dirname, '../../../.xcmax/mod-pilot.env'),
  ].filter(Boolean) as string[]
  for (const file of candidates) {
    if (!fs.existsSync(file)) continue
    for (const raw of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
      const line = raw.trim()
      if (!line || line.startsWith('#') || !line.includes('=')) continue
      const i = line.indexOf('=')
      const key = line.slice(0, i).trim()
      let val = line.slice(i + 1).trim()
      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1)
      }
      if (key && process.env[key] === undefined) process.env[key] = val
    }
    break
  }
}
loadPilotEnvFile()

const SANDBOX_BUYER = process.env.MOD_PILOT_ALIPAY_BUYER || ''
const SANDBOX_BUYER_PASS = process.env.MOD_PILOT_ALIPAY_BUYER_PASS || ''
/** 无买家账号时：打开支付宝页后由人工扫码/登录付 0.01，脚本只轮询 paid */
const MANUAL_PAY = process.env.MOD_PILOT_ALIPAY_MANUAL === '1'

test.describe.configure({ mode: 'serial' })
test.setTimeout(MANUAL_PAY ? 600_000 : 300_000)

test.beforeAll(async () => {
  fs.mkdirSync(EVIDENCE, { recursive: true })
  // Mod 试点依赖独立 MODstore；未启动时跳过整组（见 scripts/dev/run_mod_pilot_local.sh）
  try {
    const res = await fetch(`${MARKET_API}/api/health`, { signal: AbortSignal.timeout(5000) })
    if (!res.ok) test.skip(true, `MODstore 未就绪: ${MARKET_API}`)
  } catch {
    test.skip(true, `MODstore 未启动 (${MARKET})，跳过 mod-pilot 证据流`)
  }
})

async function shot(page: import('@playwright/test').Page, file: string) {
  await page.screenshot({ path: path.join(EVIDENCE, file), fullPage: true })
}

async function marketToken(username: string, password: string): Promise<string> {
  const res = await fetch(`${MARKET_API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  expect(res.ok).toBeTruthy()
  const body = await res.json()
  const token = body.access_token || body.token
  expect(token).toBeTruthy()
  return String(token)
}

async function marketLogin(page: import('@playwright/test').Page, redirectPath: string, user: string, pass: string) {
  const token = await marketToken(user, pass)
  await page.goto(MARKET, { waitUntil: 'domcontentloaded' })
  await page.evaluate(
    ([accessToken, refreshToken]) => {
      localStorage.setItem('modstore_token', accessToken)
      if (refreshToken) localStorage.setItem('modstore_refresh_token', refreshToken)
    },
    [token, ''],
  )
  await page.goto(`${MARKET}${redirectPath}`, { waitUntil: 'domcontentloaded', timeout: 60_000 })
  return token
}

async function openModStore(page: import('@playwright/test').Page) {
  // 默认 tab=host_foundation 可能空目录；证据页直接进「已安装」
  const storeUrl = `${FHD_WEB}/mod-store?tab=installed`
  await page.goto(storeUrl, { waitUntil: 'domcontentloaded', timeout: 90_000 })
  const store = page.locator('.mod-store.store-page')
  if (!(await store.isVisible({ timeout: 20_000 }).catch(() => false))) {
    await page.goto(`${FHD_WEB}/ai-ecosystem`, { waitUntil: 'domcontentloaded', timeout: 60_000 })
    const launcher = page.locator('[data-tour="ecosystem-launcher-modstore"]').first()
    await expect(launcher).toBeVisible({ timeout: 20_000 })
    await launcher.click()
    await page.waitForURL(/\/mod-store/, { timeout: 30_000 })
    await page.goto(storeUrl, { waitUntil: 'domcontentloaded', timeout: 60_000 })
  }
  await expect(page.locator('.mod-store.store-page')).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.store-title')).toContainText('AI 员工市场', { timeout: 30_000 })
}

async function fhdEnterpriseLogin(page: import('@playwright/test').Page, redirectPath = '/mod-store') {
  // 走前端同源代理拿 csrf_token + session_id（与 e2e/helpers.loginBrowserSession 一致）
  const web = FHD_WEB.replace(/\/$/, '')
  await page.request.get(`${web}/api/health`, { timeout: 15_000 })
  const pre = await page.request.storageState()
  const csrf = pre.cookies.find((c) => c.name === 'csrf_token')?.value || pre.cookies.find((c) => c.name === 'csrf-token')?.value || ''
  const resp = await page.request.post(`${web}/api/auth/login`, {
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
    },
    data: { username: MERCHANT_USER, password: MERCHANT_PASS, account_kind: 'enterprise' },
    timeout: 30_000,
  })
  const body = await resp.json().catch(() => ({}) as Record<string, unknown>)
  expect(resp.ok(), `FHD login HTTP ${resp.status()} ${JSON.stringify(body).slice(0, 200)}`).toBeTruthy()
  expect(body.success, String(body.message || body.error_code || 'login failed')).toBeTruthy()
  await page.context().addCookies((await page.request.storageState()).cookies)

  const marketToken = String(body.market_access_token || '')
  await page.goto(web, { waitUntil: 'domcontentloaded', timeout: 60_000 })
  await page.evaluate((tok) => {
    // 不要强开 platform shell：冷启动 filter 与守卫时序会导致首跳不稳定
    localStorage.removeItem('xcagi_platform_shell_mode')
    if (tok) {
      localStorage.setItem('xcagi_market_access_token', tok)
      localStorage.setItem('modstore_token', tok)
    }
  }, marketToken)

  // 等主壳就绪，再进能力库
  await page
    .locator('.app-shell.is-ready, [aria-label="品牌与标题"]')
    .first()
    .waitFor({ state: 'visible', timeout: 60_000 })
    .catch(() => undefined)

  const splash = page.locator('[aria-label*="初始化"], [title*="跳过"], button:has-text("跳过")').first()
  if (await splash.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await splash.click()
  }

  if (redirectPath.includes('mod-store')) {
    await openModStore(page)
  } else {
    await page.goto(`${web}${redirectPath}`, { waitUntil: 'domcontentloaded', timeout: 90_000 })
  }
}

async function trySandboxPay(page: import('@playwright/test').Page) {
  if (!SANDBOX_BUYER || !SANDBOX_BUYER_PASS) return
  const buyerInput = page.locator('input[name="logonId"], input#logonId, input[placeholder*="支付宝"]').first()
  if (await buyerInput.isVisible({ timeout: 8_000 }).catch(() => false)) {
    await buyerInput.fill(SANDBOX_BUYER)
    const pwd = page.locator('input[type="password"]').first()
    if (await pwd.isVisible().catch(() => false)) await pwd.fill(SANDBOX_BUYER_PASS)
    const loginBtn = page.getByRole('button', { name: /登录|下一步|Next/i }).first()
    if (await loginBtn.isVisible().catch(() => false)) await loginBtn.click()
  }
  const payBtn = page.getByRole('button', { name: /确认付款|立即支付|Pay Now|确认/i }).first()
  if (await payBtn.isVisible({ timeout: 15_000 }).catch(() => false)) {
    await payBtn.click()
  }
}

async function waitOrderPaid(token: string, orderId: string, timeoutMs = 180_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const res = await fetch(`${MARKET_API}/api/payment/query/${encodeURIComponent(orderId)}?reconcile=true`, {
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
    })
    if (res.ok) {
      const data = await res.json()
      if (String(data.status).toLowerCase() === 'paid') return data
    }
    await new Promise((r) => setTimeout(r, 2000))
  }
  throw new Error(`订单 ${orderId} 在 ${timeoutMs / 1000}s 内未变为 paid（需完成支付宝沙箱付款）`)
}

test('01-listing · admin catalog', async ({ page }) => {
  await marketLogin(page, '/admin/database', ADMIN_USER, ADMIN_PASS)
  await expect(page.getByRole('heading', { name: '数据库管理' })).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.db-section').filter({ hasText: '商品目录' }).locator('tbody tr').first()).toBeVisible({
    timeout: 30_000,
  })
  await shot(page, '01-listing.png')
})

test('02-store-page · ai-store', async ({ page }) => {
  await marketLogin(page, '/ai-store', MERCHANT_USER, MERCHANT_PASS)
  await shot(page, '02-store-page.png')
})

function parseOrderIdFromAlipayUrl(url: string): string {
  try {
    const u = new URL(url)
    const biz = u.searchParams.get('biz_content')
    if (biz) {
      const parsed = JSON.parse(biz) as { out_trade_no?: string }
      if (parsed.out_trade_no) return parsed.out_trade_no
    }
  } catch {
    /* fall through */
  }
  const m = url.match(/out_trade_no[=:%22]+(MOD[0-9A-Za-z]+)/)
  return m?.[1] || ''
}

test('03-payment · 真实 checkout + 沙箱 0.01', async ({ page }) => {
  test.skip(
    !(SANDBOX_BUYER && SANDBOX_BUYER_PASS) && !MANUAL_PAY,
    '需 MOD_PILOT_ALIPAY_BUYER/PASS，或 MOD_PILOT_ALIPAY_MANUAL=1 人工付 0.01（可写 ~/.xcmax/mod-pilot.env）',
  )
  const token = await marketLogin(page, '/recharge', MERCHANT_USER, MERCHANT_PASS)
  await page.locator('input.custom-input, input[type="number"]').first().fill('0.01')
  await page.getByRole('button', { name: '立即支付' }).click()
  await page.getByRole('button', { name: '继续' }).click()
  await page.waitForURL(/alipaydev|alipay\.com|gateway\.do/i, { timeout: 90_000 })
  const orderId = parseOrderIdFromAlipayUrl(page.url())
  expect(orderId).toMatch(/^MOD/)
  if (SANDBOX_BUYER && SANDBOX_BUYER_PASS) {
    await trySandboxPay(page)
  } else {
    // 人工模式：保留支付宝页，等沙箱买家扫码/登录完成付款
    // eslint-disable-next-line no-console
    console.log(`[mod-pilot] 请在打开的支付宝沙箱页完成 0.01 元付款（order=${orderId}），脚本最长等 8 分钟…`)
    await shot(page, '03-payment-checkout-open.png')
  }
  await waitOrderPaid(token, orderId, MANUAL_PAY ? 480_000 : 180_000)
  await marketLogin(page, '/wallet', MERCHANT_USER, MERCHANT_PASS)
  await expect(page.getByText('当前余额')).toBeVisible({ timeout: 30_000 })
  const text = await page.locator('body').innerText()
  expect(text).toMatch(/0\.01|支付宝|alipay|wallet/i)
  await shot(page, '03-payment.png')
})

test('04-activated · FHD mod-store installed', async ({ page }) => {
  // 探针：API 直连可登录再跑 UI（避免冷启动误 skip）
  const probe = await fetch(`${FHD_API.replace(/\/$/, '')}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      username: MERCHANT_USER,
      password: MERCHANT_PASS,
      account_kind: 'enterprise',
    }),
  }).catch(() => null)
  if (!probe?.ok) {
    const detail = probe ? await probe.text().catch(() => '') : 'network'
    test.skip(true, `FHD 企业商家登录不可用，跳过 mod-store 激活截图 (${detail.slice(0, 120)})`)
  }

  await fhdEnterpriseLogin(page, '/mod-store')
  await expect(page).toHaveURL(/\/mod-store/, { timeout: 30_000 })
  const storeRoot = page.locator('.mod-store.store-page')
  await expect(storeRoot).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.store-title')).toContainText('AI 员工市场')

  // 「已安装」tab 应直接露出本机已装卡；若仍空则切全部并点安装
  const installed = page.locator('.store-card--installed, .tag-owned').first()
  if (!(await installed.isVisible({ timeout: 25_000 }).catch(() => false))) {
    await page
      .getByRole('button', { name: '全部商品' })
      .click()
      .catch(() => undefined)
    page.once('dialog', (d) => d.accept().catch(() => undefined))
    const installBtn = page
      .locator('.store-card')
      .getByRole('button', { name: /^安装$/ })
      .first()
    if (await installBtn.isVisible({ timeout: 10_000 }).catch(() => false)) {
      await installBtn.click()
    } else {
      await page.locator('[data-tour="store-one-click-install"]').click({ timeout: 10_000 })
    }
    await page.goto(`${FHD_WEB}/mod-store?tab=installed`, { waitUntil: 'domcontentloaded' })
    await expect(page.locator('.store-card--installed, .tag-owned').first()).toBeVisible({
      timeout: 90_000,
    })
  }
  await expect(page.getByText('已安装').first()).toBeVisible()
  await shot(page, '04-activated.png')
})
