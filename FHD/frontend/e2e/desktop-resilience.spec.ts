import { expect, test } from '@playwright/test'
import { installE2eShellMocks, isFullStack, loginBrowserSession } from './helpers'

test.describe('desktop resilience', () => {
  test.beforeEach(async ({ page }) => {
    if (isFullStack()) await loginBrowserSession(page)
    else await installE2eShellMocks(page)
  })

  test('supported viewport matrix keeps the shell usable and labeled', async ({ page }) => {
    for (const viewport of [
      { width: 1180, height: 760 },
      { width: 1440, height: 920 },
      { width: 1920, height: 1080 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
      await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
      const overflow = await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth))
      expect(overflow, `horizontal overflow at ${viewport.width}x${viewport.height}`).toBeLessThanOrEqual(2)
    }

    const mainNav = page.locator('nav[aria-label="主导航"]')
    await expect(mainNav).toBeVisible()
    const unlabeledButtons = await mainNav.locator('button:visible').evaluateAll(
      (buttons) =>
        buttons.filter((button) => {
          const element = button as HTMLElement
          return !(element.getAttribute('aria-label') || element.getAttribute('title') || element.textContent?.trim())
        }).length,
    )
    expect(unlabeledButtons).toBe(0)
  })

  test('temporary offline state does not crash the shell and reconnects', async ({ page, context }) => {
    test.skip(!isFullStack(), 'requires the mandatory live desktop backend')
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })

    await context.setOffline(true)
    const offlineResult = await page.evaluate(async () => {
      try {
        await fetch('/api/health', { cache: 'no-store' })
        return 'unexpected-success'
      } catch {
        return 'offline'
      }
    })
    expect(offlineResult).toBe('offline')
    await expect(page.locator('.app-shell.is-ready')).toBeVisible()

    await context.setOffline(false)
    await expect
      .poll(() => page.evaluate(async () => (await fetch('/api/health', { cache: 'no-store' })).status), { timeout: 15_000 })
      .toBe(200)
    await expect(page.locator('.app-shell.is-ready')).toBeVisible()
  })
})
