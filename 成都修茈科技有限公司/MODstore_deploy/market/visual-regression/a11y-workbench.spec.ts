import { test, expect } from '@playwright/test'
import { capture, isolate } from './capture'

test.use({ deviceScaleFactor: 2 })

for (const colorScheme of ['light', 'dark'] as const) {
  for (const [width, height] of [[375, 812], [768, 1024]]) {
    test('market a11y keyboard ' + colorScheme + '-' + width, async ({ page, baseURL }) => {
      await page.setViewportSize({ width, height })
      await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
      await isolate(page, baseURL!)
      const origin = new URL(baseURL!).origin
      await page.addInitScript(() => {
        localStorage.setItem('modstore_token', 'visual-synthetic')
        localStorage.setItem('workbench_direct_conversations_v1', '[]')
        localStorage.setItem('workbench_direct_active_v1', '')
      })
      await page.route('**/api/**', async route => {
        const url = new URL(route.request().url())
        if (url.origin !== origin) return route.abort('blockedbyclient')
        if (!url.pathname.startsWith('/api/')) return route.fallback()
        if (url.pathname === '/api/auth/me') return route.fulfill({ json: { id: 1, username: 'tester', is_admin: false } })
        if (url.pathname === '/api/notifications') return route.fulfill({ json: { items: [], unread_count: 0 } })
        if (url.pathname === '/api/wallet/balance') return route.fulfill({ json: { balance: 0 } })
        return route.fulfill({ json: {} })
      })
      await page.goto('/workbench/home')
      const input = page.locator('#wb-home-input')
      await expect(input).toBeVisible({ timeout: 30000 })
      await input.fill('请核对订单差异')
      await input.focus()
      await expect(input).toBeFocused()
      // Check the keyboard focus indicator, not merely the active element.
      await input.evaluate(element => (element as HTMLElement).blur())
      const unfocused = await input.evaluate(element => {
        const style = getComputedStyle(element)
        return style.outline + '|' + style.boxShadow
      })
      await input.focus()
      const focused = await input.evaluate(element => {
        const style = getComputedStyle(element)
        return style.outline + '|' + style.boxShadow
      })
      expect(focused, 'focused input must visibly differ from its idle state').not.toBe(unfocused)
      await capture(page, 'a11y-workbench-focused-' + colorScheme + '-' + width, 'device')
      await page.keyboard.press('Tab')
      expect(await page.evaluate(() => !!document.activeElement && document.activeElement !== document.body)).toBe(true)
      expect(await page.evaluate(() => document.activeElement?.matches(':focus-visible'))).toBe(true)
      await capture(page, 'a11y-workbench-tab-' + colorScheme + '-' + width, 'device')
    })
  }
}
