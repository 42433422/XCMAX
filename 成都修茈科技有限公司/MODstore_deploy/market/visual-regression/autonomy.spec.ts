import { test, expect } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { capture, isolate } from './capture'

const controlSource = new URL('../src/components/floating-agent/XiaoCLifeControl.vue', import.meta.url)
const baselineLacksPopover = process.env.VISUAL_CAPTURE_SIDE === 'baseline'
  && (!existsSync(controlSource) || !readFileSync(controlSource, 'utf8').includes('data-xiaoc-autonomy-trigger'))

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

const touchTest = test.extend({ hasTouch: true })

for (const [width, height] of [[1440, 900], [375, 812]]) {
  const viewportTest = width === 375 ? touchTest : test
  viewportTest('autonomy popover keyboard and touch viewport ' + width, async ({ page, baseURL }) => {
    test.skip(baselineLacksPopover, 'New autonomy popover absent from base; explicit visual review required')
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
      if (!url.pathname.startsWith('/api/')) return route.fallback()
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
    const balanceSuggestion = page.getByRole('status').filter({ hasText: '余额仅剩' })
    await expect(balanceSuggestion).toBeVisible()
    await ball.click()
    await expect(balanceSuggestion).toBeHidden()
    const trigger = page.locator('[data-xiaoc-autonomy-trigger]')
    await expect(trigger).toBeVisible({ timeout: 30000 })
    await expect(trigger).toHaveText('自主任务')
    await capture(page, 'autonomy-collapsed-' + width)
    if (width === 375) await trigger.tap()
    else await trigger.click()
    const popup = page.locator('.xiaoc-autonomy-popover .xiaoc-life-control--compact')
    await expect(popup).toBeVisible()
    await expect(popup).toBeInViewport({ ratio: 1 })
    const thumb = popup.getByRole('slider')
    await expect(thumb).toHaveAttribute('aria-valuenow', '4')
    await thumb.click({ trial: true })
    await capture(page, 'autonomy-open-' + width)
    if (process.env.VISUAL_CAPTURE_SIDE === 'baseline') {
      await thumb.focus()
      await page.keyboard.press('ArrowRight')
      await capture(page, 'autonomy-preview-' + width)
      return
    }
    const value = popup.locator('.xiaoc-life-control__value')
    await expect(value).toHaveText('L4 · 自治运营')
    await expect(popup.getByRole('button')).toHaveCount(0)
    if (width === 375) {
      const runway = popup.locator('.el-slider__runway')
      const box = await runway.boundingBox()
      expect(box).not.toBeNull()
      await runway.tap({ position: { x: box!.width * 0.8, y: box!.height / 2 } })
    } else {
      await thumb.focus()
      await thumb.press('ArrowRight')
      await expect(thumb).toHaveAttribute('aria-valuetext', /^L5 · /)
      await expect(value).toHaveText('L5 · 自主成长')
      await page.keyboard.press('Enter')
    }
    const dialog = page.getByRole('dialog', { name: '切换自主任务档位' })
    await expect(popup).toBeHidden()
    await expect(dialog).toContainText('L5 · 自主成长')
    await expect(dialog.getByRole('button', { name: '确认切换' })).toBeEnabled()
    await capture(page, 'autonomy-preview-' + width)
    await dialog.getByRole('button', { name: '取消' }).click()
    await expect(trigger).toBeFocused()
    await trigger.click()
    await expect(thumb).toHaveAttribute('aria-valuetext', 'L4 · 自治运营')
    await page.getByRole('button', { name: '工作动态' }).click()
    await page.getByRole('button', { name: '自主状态' }).click()
    await expect(page.getByRole('button', { name: '暂停自主活动' })).toBeVisible()
    await expect(page.getByRole('button', { name: '设置预算' })).toBeVisible()
    expect(lifeWrites).toBe(0)
  })
}
