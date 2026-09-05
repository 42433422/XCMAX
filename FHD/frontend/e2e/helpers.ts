import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { expect, type APIRequestContext, type Page } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export const E2E_USER = process.env.E2E_USER || 'xcagi-enterprise-demo'
export const E2E_PASSWORD = process.env.E2E_PASSWORD || 'Demo@2026'
export const E2E_ACCOUNT_KIND = process.env.E2E_ACCOUNT_KIND || 'enterprise'
type BrowserCookie = Awaited<ReturnType<APIRequestContext['storageState']>>['cookies'][number]

const loginCookieCache = new Map<string, Promise<BrowserCookie[]>>()

class InvalidE2ESessionError extends Error {}
export function isFullStack(): boolean {
  return process.env.E2E_FULL_STACK === '1'
}

/**
 * P0 证据截图目录。
 *
 * 只有真实全栈验收才默认刷新仓库内的验收证据；本地/CI mock smoke 写入
 * 已忽略的 Playwright 报告目录，避免一键发布门禁污染候选工作树。
 */
export function evidenceDir(): string {
  if (process.env.E2E_EVIDENCE_DIR) return process.env.E2E_EVIDENCE_DIR
  if (isFullStack()) return path.join(__dirname, '../../docs/evidence/e2e')
  return path.join(__dirname, '../playwright-report/evidence')
}

export async function captureEvidence(page: Page, filename: string): Promise<void> {
  const dir = evidenceDir()
  fs.mkdirSync(dir, { recursive: true })
  await page.screenshot({ path: path.join(dir, filename), fullPage: false })
}

const E2E_SESSION_PAYLOAD = {
  success: true,
  valid: true,
  data: {
    valid: true,
    username: 'e2e-user',
    role: 'user',
    account_kind: 'personal',
  },
}

/** 绕过 App.vue 启动鉴权 + 企业版路由守卫，使主壳可测。 */
export async function installE2eShellMocks(page: Page): Promise<void> {
  await page.route('**/api/runtime/product-sku**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { sku: 'personal' } }),
    })
  })
  await page.route('**/api/auth/session/validate**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(E2E_SESSION_PAYLOAD),
    })
  })
  await page.route('**/api/auth/me**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          user: { id: 1, username: 'e2e-user', role: 'user' },
          permissions: [],
        },
      }),
    })
  })
}

/** @deprecated 使用 installE2eShellMocks */
export const installPersonalSkuMocks = installE2eShellMocks

const LOGIN_RETRY_DELAYS_MS = [1_000, 2_000, 4_000, 8_000] as const

function isTransientLoginError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return (
    message.includes('transient failure') ||
    message.includes('Timeout') ||
    message.includes('timed out') ||
    message.includes('ECONNRESET') ||
    message.includes('ECONNREFUSED')
  )
}

async function waitBeforeLoginRetry(attempt: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, LOGIN_RETRY_DELAYS_MS[attempt]))
}

/** 与 pytest ``_csrf_headers`` 一致：先打 health 拿 csrf_token cookie。 */
export async function csrfHeaders(
  request: APIRequestContext,
  extra: Record<string, string> = {},
  apiBase = '',
): Promise<Record<string, string>> {
  const base = apiBase.replace(/\/$/, '')
  await request.get(`${base}/api/health`, { timeout: 15_000 })
  const state = await request.storageState()
  const csrf = state.cookies.find((c) => c.name === 'csrf_token')?.value || state.cookies.find((c) => c.name === 'csrf-token')?.value || ''
  return {
    'Content-Type': 'application/json',
    ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
    ...extra,
  }
}

async function createLoginCookies(request: APIRequestContext, base: string): Promise<BrowserCookie[]> {
  let lastTransientError: unknown
  for (let attempt = 0; attempt <= LOGIN_RETRY_DELAYS_MS.length; attempt += 1) {
    try {
      const headers = await csrfHeaders(request, {}, base)
      const resp = await request.post(`${base}/api/auth/login`, {
        headers,
        data: {
          username: E2E_USER,
          password: E2E_PASSWORD,
          account_kind: E2E_ACCOUNT_KIND,
        },
        timeout: 20_000,
      })
      const body = await resp.json().catch(() => ({}))
      if (resp.status() >= 500) {
        throw new Error(`E2E login transient failure: status=${resp.status()} body=${JSON.stringify(body)}`)
      }
      if (body?.success !== true) {
        throw new Error(`E2E login failed: status=${resp.status()} body=${JSON.stringify(body)}`)
      }
      return (await request.storageState()).cookies
    } catch (error) {
      if (!isTransientLoginError(error) || attempt === LOGIN_RETRY_DELAYS_MS.length) throw error
      lastTransientError = error
      await waitBeforeLoginRetry(attempt)
    }
  }

  throw lastTransientError
}

async function assertCurrentBrowserSession(page: Page, base: string): Promise<void> {
  let lastTransientError: unknown
  for (let attempt = 0; attempt <= LOGIN_RETRY_DELAYS_MS.length; attempt += 1) {
    try {
      const meResp = await page.request.get(`${base}/api/auth/me`, { timeout: 20_000 })
      const meBody = await meResp.json().catch(() => ({}))
      if (meResp.status() >= 500) {
        throw new Error(`E2E auth verification transient failure: status=${meResp.status()} body=${JSON.stringify(meBody)}`)
      }
      if (meBody?.success !== true || !meBody?.data?.user) {
        throw new InvalidE2ESessionError(`E2E auth verification failed: status=${meResp.status()} body=${JSON.stringify(meBody)}`)
      }
      return
    } catch (error) {
      if (error instanceof InvalidE2ESessionError || !isTransientLoginError(error) || attempt === LOGIN_RETRY_DELAYS_MS.length) {
        throw error
      }
      lastTransientError = error
      await waitBeforeLoginRetry(attempt)
    }
  }
  throw lastTransientError
}

export async function loginBrowserSession(page: Page, apiBase = ''): Promise<void> {
  const base = (apiBase || process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5001').replace(/\/$/, '')
  let cookiePromise = loginCookieCache.get(base)
  if (!cookiePromise) {
    cookiePromise = createLoginCookies(page.request, base)
    loginCookieCache.set(base, cookiePromise)
  }

  let cookies: BrowserCookie[]
  try {
    cookies = await cookiePromise
  } catch (error) {
    if (loginCookieCache.get(base) === cookiePromise) loginCookieCache.delete(base)
    throw error
  }
  await page.context().addCookies(cookies)

  try {
    await assertCurrentBrowserSession(page, base)
  } catch (error) {
    if (!(error instanceof InvalidE2ESessionError)) throw error
    loginCookieCache.delete(base)
    await page.context().clearCookies()
    const freshCookiePromise = createLoginCookies(page.request, base)
    loginCookieCache.set(base, freshCookiePromise)
    const freshCookies = await freshCookiePromise
    await page.context().addCookies(freshCookies)
    await assertCurrentBrowserSession(page, base)
  }
  await bindErpWorkspace(page.request, base)
}

/** ERP cases start after industry selection, using the same persisted workspace as the UI. */
async function bindErpWorkspace(request: APIRequestContext, base: string): Promise<string> {
  const catalogResponse = await request.get(`${base}/api/platform-shell/onboarding-industries`)
  expect(catalogResponse.ok(), await catalogResponse.text()).toBe(true)
  const catalogBody = await catalogResponse.json()
  expect(catalogBody.success).toBe(true)
  const catalog = catalogBody.data || catalogBody
  const ownerId = catalog.owner_id
  expect(typeof ownerId).toBe('string')
  expect(ownerId.trim()).not.toBe('')
  expect(catalog.open_packages).toEqual(expect.arrayContaining([
    expect.objectContaining({ industry_id: '涂料', selectable: true }),
  ]))

  const beforeResponse = await request.get(`${base}/api/workspace/prefs`)
  expect(beforeResponse.ok(), await beforeResponse.text()).toBe(true)
  const before = await beforeResponse.json()
  expect(before).toMatchObject({ success: true, owner_id: ownerId })
  const expected = { success: true, owner_id: ownerId, data: { selected_industry_id: '涂料' } }
  if (before.data?.selected_industry_id !== '涂料') {
    const patchedResponse = await request.patch(`${base}/api/workspace/prefs`, {
      headers: await csrfHeaders(request, {}, base),
      data: { selected_industry_id: '涂料' },
    })
    expect(patchedResponse.ok(), await patchedResponse.text()).toBe(true)
    expect(await patchedResponse.json()).toMatchObject(expected)
  }
  const readbackResponse = await request.get(`${base}/api/workspace/prefs`)
  expect(readbackResponse.ok(), await readbackResponse.text()).toBe(true)
  expect(await readbackResponse.json()).toMatchObject(expected)
  return ownerId
}

/** The separate request fixture prepares ERP state without authenticating the form's browser. */
export async function prepareErpSession(request: APIRequestContext): Promise<string> {
  const base = (process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5001').replace(/\/$/, '')
  await createLoginCookies(request, base)
  return bindErpWorkspace(request, base)
}

export async function imUserHeaders(request: APIRequestContext, userId: string): Promise<Record<string, string>> {
  return csrfHeaders(request, { 'X-User-ID': userId })
}
