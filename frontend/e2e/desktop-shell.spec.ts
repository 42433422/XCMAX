/**
 * 桌面壳 WebView：与 Web 共用 Vite 产物；Electron 加载同一 baseURL。
 * CI 在 frontend-e2e job 中以 Chromium 代理 WebView 行为。
 */
import { test, expect } from '@playwright/test'

test.describe('Desktop shell (WebView parity)', () => {
  test('loads SPA with desktop user-agent hint', async ({ browser }) => {
    const context = await browser.newContext({
      userAgent:
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 XCAGI-Desktop/9.0.0',
    })
    const page = await context.newPage()
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('#app')).toBeVisible()
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await context.close()
  })
})
