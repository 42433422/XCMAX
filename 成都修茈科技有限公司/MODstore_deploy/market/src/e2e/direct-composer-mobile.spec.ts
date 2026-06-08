import { expect, test } from '@playwright/test'

test.describe('direct chat composer mobile width', () => {
  test('input is at least 200px wide at 375px viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await page.addInitScript(() => {
      localStorage.setItem('modstore_token', 'e2e-token')
      localStorage.setItem('workbench_direct_conversations_v1', '[]')
      localStorage.setItem('workbench_direct_active_v1', '')
    })
    await page.route('**/*', async (route) => {
      const { pathname } = new URL(route.request().url())
      if (pathname === '/api/auth/me') {
        await route.fulfill({ json: { id: 1, username: 'tester', is_admin: false } })
        return
      }
      if (pathname === '/api/notifications') {
        await route.fulfill({ json: { items: [], unread_count: 0 } })
        return
      }
      if (pathname.startsWith('/api/')) {
        await route.fulfill({ json: {} })
        return
      }
      await route.continue()
    })
    await page.goto('/market/workbench/home')
    const input = page.locator('#wb-home-input')
    await expect(input).toBeVisible({ timeout: 20000 })
    const box = await input.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.width).toBeGreaterThanOrEqual(200)
  })
})
