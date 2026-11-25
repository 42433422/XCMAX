import { test, expect } from '@playwright/test'
import { capture, isolate } from './capture'

// Fixed synthetic identity. The scenario never authorizes or mutates a real company.
const lifeState = {
  identity_id: 'visual-enterprise-xiaoc', scope: 'enterprise', owner_user_id: 1,
  revision: 4, level: 4, paused: false, stopped: false, state_version: 3,
  status: 'idle', mission: '验证自主任务界面', activity: null,
  goals: [], interests: [], self_model: {}, events: [], blockers: [],
  budget: { used_tokens: 0, reserved_tokens: 0, cycles: 0, exploration_tokens: 0 },
  policy: { daily_token_limit: 100, daily_cycle_limit: 1, exploration_percent: 0,
    wake_interval_seconds: 900, authorization_expires_at: null },
  updated_at: '2026-01-15T04:00:00Z', next_wake_at: null,
}

for (const [width, height] of [[1440, 900], [375, 812]]) {
  test('autonomy popover keyboard and touch viewport ' + width, async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height })
    await isolate(page, baseURL!)
    const origin = new URL(baseURL!).origin
    await page.addInitScript(() => {
      localStorage.setItem('modstore_token', 'visual-synthetic')
      localStorage.setItem('xc_butler_consent', 'v1')
      sessionStorage.setItem('modstore_admin_digest_unlock_expires', '2027-01-01T00:00:00Z')
    })
    let lifeWrites = 0
    await page.route('**/api/**', route => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.origin !== origin) return route.abort('blockedbyclient')
      if (request.method() !== 'GET') {
        if (url.pathname === '/api/agent/butler/life') lifeWrites += 1
        return route.fulfill({ status: 403, json: { detail: 'visual read-only' } })
      }
      if (url.pathname === '/api/auth/me')
        return route.fulfill({ json: { id: 1, username: 'visual-admin', is_admin: true } })
      if (url.pathname === '/api/agent/butler/life')
        return route.fulfill({ json: lifeState })
      if (url.pathname === '/api/notifications')
        return route.fulfill({ json: { items: [], unread_count: 0 } })
      if (url.pathname === '/api/wallet/balance')
        return route.fulfill({ json: { balance: 0 } })
      return route.fulfill({ json: {} })
    })
    await page.goto('/admin/overview', { waitUntil: 'domcontentloaded' })
    const ball = page.getByRole('button', { name: '小C助理' })
    await expect(ball).toBeVisible({ timeout: 30000 })
    await ball.click()
    const trigger = page.locator('[data-xiaoc-autonomy-trigger]')
    await expect(trigger).toBeVisible({ timeout: 30000 })
    await expect(trigger).toHaveText('自主任务')
    await capture(page, 'autonomy-collapsed-' + width)
    await trigger.click()
    const popup = page.locator('.xiaoc-autonomy-popover .xiaoc-life-control--compact')
    await expect(popup).toBeVisible()
    await expect(popup).toContainText('L4')
    await capture(page, 'autonomy-open-' + width)
    const thumb = popup.locator('.el-slider__button-wrapper')
    await thumb.focus()
    await page.keyboard.press('ArrowRight')
    await expect(popup).toContainText('预选 L5')
    await capture(page, 'autonomy-preview-' + width)
    await page.keyboard.press('Escape')
    await expect(trigger).toHaveAttribute('aria-expanded', 'false')
    await expect(trigger).toBeFocused()
    expect(lifeWrites).toBe(0)
  })
}
