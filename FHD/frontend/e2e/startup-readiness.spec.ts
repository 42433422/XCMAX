import { test, expect } from '@playwright/test'
import { deferred, installStartupReadinessMocks } from './startup-readiness-fixture'
import { isFullStack } from './helpers'

const overlay = (page: import('@playwright/test').Page) => page.getByTestId('startup-readiness')
const workspace = (page: import('@playwright/test').Page) => page.getByTestId('startup-workspace')

test.describe('First usable workspace readiness', () => {
  test.skip(isFullStack(), 'deterministic synthetic API and resource fault injection')
  test.describe.configure({ timeout: 90_000 })

  test('cold and warm startup allow typing only after readiness', async ({ page }) => {
    await installStartupReadinessMocks(page)
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    for (const kind of ['cold', 'warm']) {
      const started = Date.now()
      if (kind === 'cold') await page.goto('/', { waitUntil: 'domcontentloaded' })
      else await page.reload({ waitUntil: 'domcontentloaded' })
      await expect(overlay(page)).toHaveCount(0, { timeout: 25_000 })
      await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
      await expect(workspace(page)).not.toHaveAttribute('inert')
      await page.locator('#messageInput').fill(`${kind} startup`)
      await expect(page.locator('#messageInput')).toHaveValue(`${kind} startup`)
      test.info().annotations.push({ type: 'synthetic-linux-chromium', description: `${kind}: usable after ${Date.now() - started}ms` })
    }
    expect(errors).toEqual([])
  })

  for (const path of ['/api/auth/session/validate', '/api/auth/me', '/api/system/industry', '/api/mods/']) {
    test(`holds the mounted workspace while ${path} is delayed`, async ({ page }) => {
      const mock = await installStartupReadinessMocks(page)
      const gate = deferred()
      let held = false
      mock.handlers.set(path, async (route, call) => {
        // me/industry also run inside the authoritative initial router guard.
        if (!['/api/auth/me', '/api/system/industry'].includes(path) || call > 1) {
          held = true
          await gate.promise
        }
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(
          path === '/api/auth/session/validate' ? { success: true, valid: true, data: { valid: true, username: 'startup-test-1' } }
            : path === '/api/auth/me' ? { success: true, data: { account_kind: 'personal', local_user_id: 1, user: { id: 1, username: 'startup-test-1', role: 'user' } } }
              : path === '/api/system/industry' ? { success: true, data: { id: '通用', name: '通用' } } : { success: true, data: [] },
        ) })
      })
      try {
        await page.goto('/', { waitUntil: 'domcontentloaded' })
        await expect.poll(() => held, { timeout: 20_000 }).toBe(true)
        await expect(overlay(page)).toHaveAttribute('data-state', 'loading')
        await expect(workspace(page)).toHaveAttribute('inert')
        expect(await page.locator('#messageInput').evaluate(element => (element as HTMLElement).closest('[inert]') !== null)).toBe(true)
        await page.locator('#messageInput').evaluate(element => (element as HTMLElement).focus())
        await expect(page.locator('#messageInput')).not.toBeFocused()
        if (path === '/api/mods/') {
          // The former six-second failsafe must not report success during a real delay.
          await page.waitForTimeout(6_300)
          await expect(overlay(page)).toHaveAttribute('data-state', 'loading')
          await expect(page.locator('.app-shell.is-ready')).toHaveCount(0)
        }
      } finally { gate.release() }
      await expect(overlay(page)).toHaveCount(0, { timeout: 25_000 })
      await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    })
  }

  test('waits for the local icon font and releases after it loads', async ({ page }) => {
    await installStartupReadinessMocks(page)
    const gate = deferred()
    let requested = false
    await page.route(/fontawesome-webfont\.(woff2|woff|ttf)(\?|$)/, async route => {
      requested = true
      await gate.promise
      await route.continue()
    })
    try {
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      await expect.poll(() => requested, { timeout: 20_000 }).toBe(true)
      await expect(overlay(page)).toContainText('正在准备图标和页面', { timeout: 20_000 })
      await expect(overlay(page)).toHaveAttribute('data-state', 'loading')
      await expect(workspace(page)).toHaveAttribute('inert')
    } finally { gate.release() }
    await expect(overlay(page)).toHaveCount(0, { timeout: 25_000 })
    expect(await page.evaluate(() => document.fonts.check('14px FontAwesome', '\uf015'))).toBe(true)
  })

  test('timeout exposes recovery and a late resource cannot dismiss the error', async ({ page }) => {
    await installStartupReadinessMocks(page)
    const gate = deferred()
    await page.route(/fontawesome-webfont\.(woff2|woff|ttf)(\?|$)/, async route => {
      await gate.promise
      await route.continue()
    })
    try {
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      await expect(overlay(page)).toContainText('正在准备图标和页面', { timeout: 20_000 })
      const started = Date.now()
      await expect(overlay(page)).toHaveAttribute('data-state', 'error', { timeout: 25_000 })
      await expect(overlay(page)).toContainText('超时')
      await expect(workspace(page)).toHaveAttribute('inert')
      test.info().annotations.push({ type: 'synthetic-linux-chromium', description: `font wait reached recoverable deadline after ${Date.now() - started}ms` })
    } finally { gate.release() }
    await page.waitForTimeout(200)
    await expect(overlay(page)).toHaveAttribute('data-state', 'error')
    await overlay(page).getByRole('button', { name: '重试', exact: true }).click()
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await expect(overlay(page)).toHaveCount(0)
  })

  test('a required failure stays blocked through repeated retries, then recovers', async ({ page }) => {
    const mock = await installStartupReadinessMocks(page)
    mock.handlers.set('/api/mods/', async route => {
      await route.fulfill({ status: 500, contentType: 'application/json', body: '{"success":false}' })
    })
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    for (let attempt = 0; attempt < 3; attempt++) {
      await expect(overlay(page)).toHaveAttribute('data-state', 'error', { timeout: 25_000 })
      await expect(workspace(page)).toHaveAttribute('inert')
      await expect(page.locator('.app-shell.is-ready')).toHaveCount(0)
      if (attempt < 2) await overlay(page).getByRole('button', { name: '重试', exact: true }).click()
    }
    mock.handlers.delete('/api/mods/')
    await overlay(page).getByRole('button', { name: '重试', exact: true }).click()
    await expect(overlay(page)).toHaveCount(0, { timeout: 25_000 })
    await page.locator('#messageInput').fill('recovered')
  })

  test('cancel and relogin retire the old pending request', async ({ page }) => {
    const mock = await installStartupReadinessMocks(page)
    const old = deferred(), current = deferred()
    let oldRequested = false, newRequested = false, phase = 0
    mock.handlers.set('/api/auth/session/validate', async route => {
      if (phase === 0) { oldRequested = true; await old.promise }
      else { newRequested = true; await current.promise }
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true,"valid":true,"data":{"valid":true}}' })
    })
    try {
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      await expect.poll(() => oldRequested, { timeout: 20_000 }).toBe(true)
      await overlay(page).getByRole('button', { name: '取消', exact: true }).click()
      await expect(page.locator('#lv-username')).toBeVisible()
      await expect(overlay(page)).toHaveCount(0)
      phase = 1; mock.setUser(2)
      await page.locator('#lv-username').fill('startup-test-2')
      await page.locator('#lv-password').fill('Synthetic@2026')
      await page.locator('.login-submit').click()
      await expect.poll(() => newRequested, { timeout: 20_000 }).toBe(true)
      await expect(overlay(page)).toHaveAttribute('data-state', 'loading')
      old.release()
      await page.waitForTimeout(150)
      await expect(overlay(page)).toHaveAttribute('data-state', 'loading')
      await expect(workspace(page)).toHaveAttribute('inert')
    } finally { old.release(); current.release() }
    await expect(overlay(page)).toHaveCount(0, { timeout: 25_000 })
    await expect(page.locator('#messageInput')).toBeVisible()
  })
})

test.describe('Real initial ChatView conversation readiness', () => {
  test.skip(isFullStack(), 'deterministic synthetic API and real ChatView fault injection')
  test.describe.configure({ timeout: 90_000 })
  const conversationUrl = /\/api\/conversations\/(?!sessions(?:\?|$))[^/?]+(?:\?|$)/
  const history = (id: string, text = '') => ({ success: true, id, metadata: {},
    messages: text ? [{ role: 'user', content: text, time: '12:00' }] : [] })

  for (const empty of [false, true]) {
    test(`the actual current conversation read stays masked until its ${empty ? 'legal empty' : 'nonempty'} response`, async ({ page }) => {
      await installStartupReadinessMocks(page)
      const gate = deferred()
      let requested = false
      await page.route(conversationUrl, async route => {
        requested = true
        await gate.promise
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(
          history(new URL(route.request().url()).pathname.split('/').pop()!, empty ? '' : 'initial server conversation restored'),
        ) })
      })
      try {
        await page.goto('/', { waitUntil: 'domcontentloaded' })
        await expect.poll(() => requested, { timeout: 20_000 }).toBe(true)
        // Observe the real mounted stores/fonts; no Suspense or page component is replaced.
        await expect.poll(() => page.evaluate(() => {
          const app = (document.querySelector('#app') as unknown as { __vue_app__: { config: { globalProperties: { $pinia: { _s: Map<string, { workspaceReady?: boolean; isLoaded?: boolean }> } } } } }).__vue_app__
          const stores = app.config.globalProperties.$pinia._s
          return stores.get('accountProfile')?.workspaceReady && stores.get('mods')?.isLoaded && document.fonts.check('14px FontAwesome', '\uf015')
        }), { timeout: 20_000 }).toBe(true)
        await expect(page.locator('#messageInput')).toBeAttached()
        await expect(overlay(page)).toHaveAttribute('data-state', 'loading')
        await expect(workspace(page)).toHaveAttribute('inert')
        await expect(page.locator('.app-shell.is-ready')).toHaveCount(0)
      } finally { gate.release() }
      await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
      await expect(overlay(page)).toHaveCount(0)
      if (!empty) await expect(page.locator('#view-chat')).toContainText('initial server conversation restored')
      await page.locator('#messageInput').fill('conversation is ready')
    })
  }

  for (const status of [500, 404, 200]) {
    test(`conversation ${status === 200 ? 'rejected payload' : `HTTP ${status}`} stays blocked and retry performs a fresh read`, async ({ page }) => {
      await installStartupReadinessMocks(page)
      let failing = true, reads = 0
      await page.route(conversationUrl, async route => {
        reads++
        await route.fulfill({ status: failing ? status : 200, contentType: 'application/json', body: JSON.stringify(
          failing ? { success: false, message: 'Synthetic conversation unavailable' }
            : history(new URL(route.request().url()).pathname.split('/').pop()!, 'conversation recovered after fresh read'),
        ) })
      })
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      await expect(overlay(page)).toHaveAttribute('data-state', 'error', { timeout: 25_000 })
      await expect(workspace(page)).toHaveAttribute('inert')
      await expect(page.locator('.app-shell.is-ready')).toHaveCount(0)
      const failedReads = reads
      failing = false
      await overlay(page).getByRole('button', { name: '重试', exact: true }).click()
      await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
      expect(reads).toBeGreaterThan(failedReads)
      await expect(page.locator('#view-chat')).toContainText('conversation recovered after fresh read')
      await expect(overlay(page)).toHaveCount(0)
    })
  }

  test('cancel and a new account ignore the old conversation response while the new read is pending', async ({ page }) => {
    const mock = await installStartupReadinessMocks(page)
    const old = deferred(), current = deferred()
    let phase = 0, oldRequested = false, newRequested = false
    await page.route(conversationUrl, async route => {
      const oldAccount = phase === 0
      if (oldAccount) { oldRequested = true; await old.promise }
      else { newRequested = true; await current.promise }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(
        history(new URL(route.request().url()).pathname.split('/').pop()!, oldAccount ? 'old account private server conversation' : 'new account server conversation'),
      ) })
    })
    try {
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      await expect.poll(() => oldRequested, { timeout: 20_000 }).toBe(true)
      await overlay(page).getByRole('button', { name: '取消', exact: true }).click()
      await expect(page.locator('#lv-username')).toBeVisible()
      phase = 1; mock.setUser(2)
      await page.locator('#lv-username').fill('startup-test-2')
      await page.locator('#lv-password').fill('Synthetic@2026')
      await page.locator('.login-submit').click()
      await expect.poll(() => newRequested, { timeout: 20_000 }).toBe(true)
      old.release()
      await page.waitForTimeout(150)
      await expect(overlay(page)).toHaveAttribute('data-state', 'loading')
      await expect(workspace(page)).toHaveAttribute('inert')
      await expect(page.locator('body')).not.toContainText('old account private server conversation')
    } finally { old.release(); current.release() }
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await expect(page.locator('#view-chat')).toContainText('new account server conversation')
    await expect(page.locator('body')).not.toContainText('old account private server conversation')
  })
})
