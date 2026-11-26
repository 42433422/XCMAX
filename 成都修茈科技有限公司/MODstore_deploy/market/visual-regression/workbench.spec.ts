import { test, expect } from '@playwright/test'
import { capture, isolate } from './capture'

function checkWorkbench(width: number, height: number, scale: 'css' | 'device' = 'css') {
  test('market workbench ' + width, async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height })
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
    await expect(page.locator('.wb-direct-sub')).toHaveText('像聊天一样提问，我直接帮你分析、总结和给出可执行答案。')
    const box = await input.boundingBox()
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(200)
    await capture(page, 'workbench-empty-' + width, scale)
    await input.fill('请核对示例客户的订单进度')
    await expect(input).toHaveValue('请核对示例客户的订单进度')
    await capture(page, 'workbench-draft-' + width, scale)
    if (width === 1440) {
      await page.getByRole('button', { name: 'tester 菜单' }).click()
      await expect(page.getByRole('menuitem', { name: '钱包' })).toBeVisible()
      await capture(page, 'workbench-account-menu-' + width, scale)
    }
  })
}

checkWorkbench(1440, 900)
test.describe('mobile workbench device pixels', () => {
  test.use({ deviceScaleFactor: 2 })
  checkWorkbench(375, 812, 'device')
})
