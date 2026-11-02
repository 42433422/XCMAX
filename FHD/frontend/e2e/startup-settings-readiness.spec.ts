import { test, expect, type Page, type Route } from '@playwright/test'
import { deferred, installStartupReadinessMocks } from './startup-readiness-fixture'
import { isFullStack } from './helpers'

const overlay = (page: Page) => page.getByTestId('startup-readiness')
const workspace = (page: Page) => page.getByTestId('startup-workspace')

type Stack = { callFrames: { url: string }[]; parent?: Stack }
function fromSettings(stack?: Stack): boolean {
  return !!stack && (stack.callFrames.some(frame => frame.url.includes('/composables/settings/useSettingsMods.ts')) || fromSettings(stack.parent))
}

/** CDP observes actual fetch initiators so shared account hydration is never fault-injected by mistake. */
async function interceptSettingsRead(page: Page, path: string, handler: (route: Route) => Promise<void>) {
  const client = await page.context().newCDPSession(page)
  await client.send('Network.enable')
  await client.send('Debugger.enable')
  await client.send('Debugger.setAsyncCallStackDepth', { maxDepth: 32 })
  const sources: boolean[] = []
  const waiting: ((value: boolean) => void)[] = []
  client.on('Network.requestWillBeSent', event => {
    if (new URL(event.request.url).pathname !== path) return
    const source = fromSettings(event.initiator.stack as Stack | undefined)
    const next = waiting.shift()
    if (next) next(source)
    else sources.push(source)
  })
  await page.route(`**${path}`, async route => {
    const source = sources.length ? sources.shift() : await new Promise<boolean>(resolve => waiting.push(resolve))
    if (!source) return route.fallback()
    await handler(route)
  })
}
const industry = (unit = 'settings-ready-unit') => ({ success: true,
  data: { id: '通用', name: '通用', code: '通用', units: { primary: unit } } })
const industries = { success: true, data: { industries: [{ id: '通用', name: '通用', code: '通用' }], current: '通用' } }
async function respond(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

test.describe('Real SettingsView deep-link readiness', () => {
  test.skip(isFullStack(), 'synthetic API faults identify actual SettingsView fetches through Chromium CDP')
  test.describe.configure({ timeout: 90_000 })

  for (const path of ['/api/system/industries', '/api/system/industry']) {
    test(`the mounted /settings page waits for its own ${path} response`, async ({ page }) => {
      await installStartupReadinessMocks(page)
      const gate = deferred()
      let requested = false
      await interceptSettingsRead(page, path, async route => {
        requested = true
        await gate.promise
        await respond(route, path.endsWith('/industries') ? industries : industry())
      })
      try {
        await page.goto('/settings', { waitUntil: 'domcontentloaded' })
        await expect.poll(() => requested, { timeout: 20_000 }).toBe(true)
        await expect(page.locator('#view-settings')).toBeAttached()
        // This stage is reached after authoritative account hydration, Mods and fonts.
        await expect(overlay(page)).toContainText('正在读取当前页面', { timeout: 20_000 })
        await expect(overlay(page)).toHaveAttribute('data-state', 'loading')
        await expect(workspace(page)).toHaveAttribute('inert')
        await expect(page.locator('.app-shell.is-ready')).toHaveCount(0)
      } finally { gate.release() }
      await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
      if (path.endsWith('/industry')) await expect(page.locator('#view-settings')).toContainText('settings-ready-unit')
      await expect(overlay(page)).toHaveCount(0)
    })

    test(`a failed SettingsView ${path} read requires a fresh successful retry`, async ({ page }) => {
      await installStartupReadinessMocks(page)
      let failing = true, reads = 0
      await interceptSettingsRead(page, path, async route => {
        reads++
        await respond(route, failing ? { success: false, message: 'Synthetic Settings read failure' }
          : path.endsWith('/industries') ? industries : industry(), failing ? 500 : 200)
      })
      await page.goto('/settings', { waitUntil: 'domcontentloaded' })
      await expect(overlay(page)).toHaveAttribute('data-state', 'error', { timeout: 25_000 })
      await expect(workspace(page)).toHaveAttribute('inert')
      const failedReads = reads
      expect(failedReads).toBeGreaterThan(0)
      failing = false
      await overlay(page).getByRole('button', { name: '重试', exact: true }).click()
      await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
      expect(reads).toBeGreaterThan(failedReads)
      await expect(overlay(page)).toHaveCount(0)
    })
  }

  test('a new account keeps its Settings detail masked when the old account detail arrives late', async ({ page }) => {
    const mock = await installStartupReadinessMocks(page)
    const old = deferred(), current = deferred()
    let phase = 0, oldRequested = false, newRequested = false
    await interceptSettingsRead(page, '/api/system/industry', async route => {
      const previous = phase === 0
      if (previous) { oldRequested = true; await old.promise }
      else { newRequested = true; await current.promise }
      await respond(route, industry(previous ? 'old-account-unit' : 'new-account-unit'))
    })
    try {
      await page.goto('/settings', { waitUntil: 'domcontentloaded' })
      await expect.poll(() => oldRequested, { timeout: 20_000 }).toBe(true)
      await overlay(page).getByRole('button', { name: '取消', exact: true }).click()
      await expect(page.locator('#lv-username')).toBeVisible()
      phase = 1; mock.setUser(2)
      await page.locator('#lv-username').fill('startup-test-2')
      await page.locator('#lv-password').fill('Synthetic@2026')
      await page.locator('.login-basic').click()
      await expect.poll(() => newRequested, { timeout: 20_000 }).toBe(true)
      old.release()
      await page.waitForTimeout(150)
      await expect(overlay(page)).toHaveAttribute('data-state', 'loading')
      await expect(workspace(page)).toHaveAttribute('inert')
      await expect(page.locator('#view-settings')).not.toContainText('old-account-unit')
    } finally { old.release(); current.release() }
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await expect(page.locator('#view-settings')).toContainText('new-account-unit')
    await expect(page.locator('#view-settings')).not.toContainText('old-account-unit')
  })
})
