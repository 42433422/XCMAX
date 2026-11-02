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
      await page.locator('.login-basic').click()
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
