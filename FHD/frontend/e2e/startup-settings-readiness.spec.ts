import { test, expect, type Page, type Route } from '@playwright/test'
import { deferred, installStartupReadinessMocks } from './startup-readiness-fixture'
import { isFullStack } from './helpers'

const overlay = (page: Page) => page.getByTestId('startup-readiness')
const workspace = (page: Page) => page.getByTestId('startup-workspace')

type Stack = { callFrames: { url: string }[]; parent?: Stack }
function fromSource(stack: Stack | undefined, file: string): boolean {
  return !!stack && (stack.callFrames.some(frame => frame.url.includes(file)) || fromSource(stack.parent, file))
}

/** CDP observes actual fetch initiators so shared account hydration is never fault-injected by mistake. */
async function interceptSettingsRead(page: Page, path: string, handler: (route: Route) => Promise<void>,
  file = '/composables/settings/useSettingsMods.ts', observe?: (path: string, stack?: Stack) => void) {
  const client = await page.context().newCDPSession(page)
  await client.send('Network.enable')
  await client.send('Debugger.enable')
  await client.send('Debugger.setAsyncCallStackDepth', { maxDepth: 32 })
  const sources: boolean[] = []
  const waiting: ((value: boolean) => void)[] = []
  client.on('Network.requestWillBeSent', event => {
    const requestedPath = new URL(event.request.url).pathname
    const stack = event.initiator.stack as Stack | undefined
    observe?.(requestedPath, stack)
    if (requestedPath !== path) return
    const source = fromSource(stack, file)
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
      expect(failedReads, `Expected the Settings read to fail; observed overlay: ${await overlay(page).innerText()}`).toBeGreaterThan(0)
      failing = false
      await overlay(page).getByRole('button', { name: '重试', exact: true }).click()
      await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
      expect(reads).toBeGreaterThan(failedReads)
      await expect(overlay(page)).toHaveCount(0)
    })
  }

  test('two successful hydrations for the same account reach the real Settings read without a false account-change error', async ({ page }) => {
    const mock = await installStartupReadinessMocks(page)
    const allowHost = deferred(), releaseFirstHydration = deferred(), releaseLatestHydration = deferred()
    let settingsHydration = false, hostHydration = false, settingsReads = 0
    let verifiedBeforeHydration: boolean | undefined
    const readiness = () => page.evaluate(() => {
      const app = (document.querySelector('#app') as unknown as {
        __vue_app__?: { config: { globalProperties: { $pinia: { _s: Map<string, Record<string, unknown>> } } } }
      }).__vue_app__
      const account = app?.config.globalProperties.$pinia._s.get('accountProfile')
      return { verified: account?.workspaceReady, hydrated: account?.workspaceHydrationReady }
    })
    mock.handlers.set('/api/system/industry', async route => {
      if (hostHydration) await releaseLatestHydration.promise
      await respond(route, industry())
    })
    // The renderer is mounting account 1. Start Settings hydration A
    // before allowing AppBoot's same-account verification to produce hydration B.
    mock.handlers.set('/api/auth/session/validate', async route => {
      await allowHost.promise
      await respond(route, { success: true, valid: true, data: { valid: true, username: 'startup-test-1' } })
    })
    await interceptSettingsRead(page, '/api/system/industry', async route => {
      settingsHydration = true
      allowHost.release()
      await releaseFirstHydration.promise
      await respond(route, industry())
    }, '/composables/settings/useSettingsAccount.ts', (path, stack) => {
      if (path === '/api/system/industry' && fromSource(stack, '/composables/useStartupAuth.ts')) {
        hostHydration = true
        releaseFirstHydration.release()
      }
      if (path === '/api/system/industries' && fromSource(stack, '/composables/settings/useSettingsMods.ts')) settingsReads++
    })
    await interceptSettingsRead(page, '/api/auth/me', async route => {
      if (verifiedBeforeHydration === undefined) {
        await expect.poll(async () => typeof (await readiness()).verified).toBe('boolean')
        verifiedBeforeHydration = (await readiness()).verified as boolean
      }
      await route.fallback()
    }, '/composables/settings/useSettingsAccount.ts')
    try {
      await page.goto('/settings', { waitUntil: 'domcontentloaded' })
      await expect.poll(() => settingsHydration && hostHydration, { timeout: 20_000 }).toBe(true)
      // Existing verified data remains usable during a same-owner background
      // refresh. A new workspace entry still waits for the latest hydration.
      expect(verifiedBeforeHydration).toEqual(expect.any(Boolean))
      await expect.poll(readiness).toEqual({ verified: verifiedBeforeHydration, hydrated: false })
      test.info().annotations.push({ type: 'synthetic-same-owner-readiness',
        description: `historical workspaceReady=${verifiedBeforeHydration} retained while latest workspaceHydrationReady=false` })
      await expect(overlay(page)).toHaveAttribute('data-state', 'loading')
      await expect(workspace(page)).toHaveAttribute('inert')
      expect(settingsReads).toBe(0)
      releaseLatestHydration.release()
      // Every response is 200 for the same authenticated identity. Supersession
      // must await the latest verified hydration instead of rejecting this page.
      await expect.poll(() => settingsReads, {
        timeout: 20_000,
        message: 'Settings must perform its own list read after the two successful account hydrations',
      }).toBeGreaterThan(0)
      await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
      await expect(overlay(page)).toHaveCount(0)
      await expect.poll(readiness).toEqual({ verified: true, hydrated: true })
      await expect(page.locator('.settings-profile__name')).toContainText('startup-test-1')
    } finally { allowHost.release(); releaseFirstHydration.release(); releaseLatestHydration.release() }
  })

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
      await page.locator('.login-submit').click()
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
