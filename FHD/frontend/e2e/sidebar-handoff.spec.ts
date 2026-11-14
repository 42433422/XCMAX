import { test, expect, type Page } from '@playwright/test'
import { deferred, installStartupReadinessMocks } from './startup-readiness-fixture'
import { isFullStack } from './helpers'

async function checkSettingsScroll(page: Page) {
  const scroll = page.locator('#view-settings .settings-page__scroll')
  await expect(scroll).toBeVisible()
  // Expand real Settings sections, without injecting artificial page height.
  await scroll.locator('details').evaluateAll(nodes => nodes.forEach(node => { node.setAttribute('open', '') }))
  await expect.poll(() => scroll.evaluate(node => node.scrollHeight - node.clientHeight)).toBeGreaterThan(100)
  const top = await page.locator('.top-bar').boundingBox()
  const region = await page.locator('.route-content').boundingBox()
  const slot = await page.locator('.route-content-slot').boundingBox()
  expect(top).not.toBeNull(); expect(region).not.toBeNull(); expect(slot).not.toBeNull()
  expect(region!.y).toBeGreaterThanOrEqual(top!.y + top!.height - 1)
  expect(slot!.height).toBeLessThanOrEqual(region!.height + 1)
  expect(slot!.height).toBeGreaterThan(100)
  const viewport = page.viewportSize()!
  expect(slot!.x + slot!.width).toBeLessThanOrEqual(viewport.width + 1)
  expect(slot!.y + slot!.height).toBeLessThanOrEqual(viewport.height + 1)
  await scroll.evaluate(node => { node.scrollTop = node.scrollHeight })
  await expect.poll(() => scroll.evaluate(node => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeLessThanOrEqual(2)
  const bottom = await scroll.locator('.settings-card').last().boundingBox()
  const scrollBox = await scroll.boundingBox()
  expect(bottom).not.toBeNull()
  expect(bottom!.y + bottom!.height).toBeLessThanOrEqual(scrollBox!.y + scrollBox!.height + 1)
  expect(await page.locator('.top-bar').boundingBox()).toEqual(top)
}

test.describe('Sidebar handoff real layout', () => {
  test.skip(isFullStack(), 'isolated synthetic account and delayed Vite module')
  test.describe.configure({ timeout: 90_000 })
  for (const viewport of [{ width: 1440, height: 600 }, { width: 390, height: 600 }]) {
    test(`settings stays scrollable after rapid navigation and history at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport)
      await installStartupReadinessMocks(page)
      const gate = deferred()
      let requested = false
      await page.route('**/src/views/SettingsView.vue*', async route => {
        requested = true
        await gate.promise
        await route.continue()
      })
      try {
        await page.goto('/', { waitUntil: 'domcontentloaded' })
        await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
        await expect(page.locator('#messageInput')).toBeVisible()
        const settings = page.getByRole('button', { name: '系统设置', exact: true })
        await settings.click(); await settings.click()
        await expect.poll(() => requested).toBe(true)
        await expect(page.locator('.route-content')).toHaveAttribute('aria-busy', 'true')
        await expect(page.locator('#messageInput')).not.toBeVisible()
        await expect(page.getByTestId('route-nav-feedback')).toBeVisible()
      } finally { gate.release() }
      await expect(page).toHaveURL(/\/settings$/)
      await expect(page.locator('.route-content')).not.toHaveAttribute('aria-busy', 'true')
      await checkSettingsScroll(page)
      if (viewport.width > 768) {
        const sidebar = await page.locator('.sidebar-shell').boundingBox()
        const content = await page.locator('.main-content').boundingBox()
        expect(sidebar).not.toBeNull(); expect(content).not.toBeNull()
        expect(sidebar!.width).toBeGreaterThan(0)
        expect(sidebar!.x + sidebar!.width).toBeLessThanOrEqual(content!.x + 1)
      }
      for (let repeat = 0; repeat < 2; repeat++) {
        await page.goBack()
        await expect(page.locator('#messageInput')).toBeVisible()
        await page.goForward()
        await expect(page).toHaveURL(/\/settings$/)
        await checkSettingsScroll(page)
      }
      await test.info().attach(`settings-bottom-${viewport.width}`, { body: await page.screenshot(), contentType: 'image/png' })
    })
  }
  test('Web navigation leaves no old page overlay and history supersedes a cold load', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 600 })
    await installStartupReadinessMocks(page, false)
    const gate = deferred()
    let requested = false
    await page.route('**/src/views/SettingsView.vue*', async route => {
      requested = true
      await gate.promise
      await route.continue()
    })
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    expect(await page.evaluate(() => 'xcagiDesktop' in window)).toBe(false)
    await expect(page.locator('#messageInput')).toBeVisible()
    // Establish a same-document entry using the mounted real router.
    await page.evaluate(async () => {
      const app = document.querySelector('#app') as unknown as {
        __vue_app__: { config: { globalProperties: { $router: { push(path: string): Promise<unknown> } } } }
      }
      await app.__vue_app__.config.globalProperties.$router.push('/?history=ready')
    })
    const loaded = page.waitForResponse(response => response.url().includes('/src/views/SettingsView.vue') && response.status() === 200)
    try {
      await page.getByRole('button', { name: '系统设置', exact: true }).click()
      await expect.poll(() => requested).toBe(true)
      await expect(page.locator('#messageInput')).not.toBeVisible()
      await page.goBack()
      await expect(page).toHaveURL(/\/$/)
      await expect(page.locator('#messageInput')).toBeVisible()
    } finally { gate.release() }
    await loaded
    // Settle the released module and cancellation past the normal 100ms fade.
    await page.waitForTimeout(200)
    await expect(page).toHaveURL(/\/$/)
    await expect(page.locator('#view-settings')).not.toBeVisible()
    await expect(page.locator('#messageInput')).toBeVisible()
    await expect(page.locator('.route-content')).not.toHaveAttribute('aria-busy', 'true')
    await page.goForward()
    await expect(page).toHaveURL(/history=ready/)
    await expect(page.locator('#messageInput')).toBeVisible()
    await page.getByRole('button', { name: '系统设置', exact: true }).click()
    await expect(page.locator('#view-settings')).toBeVisible()
    await expect(page.locator('.route-fade-leave-active')).toHaveCount(0)
    await expect(page.locator('.route-content-slot #view-chat')).toHaveCount(0)
    await expect(page.locator('#messageInput')).not.toBeVisible()
    await checkSettingsScroll(page)
    await test.info().attach('web-settings-final', { body: await page.screenshot(), contentType: 'image/png' })
  })

})
