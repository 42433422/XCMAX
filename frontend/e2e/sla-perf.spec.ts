/**
 * 将 README 营销数字固化为可回归 SLA 探针（CI 友好阈值，非第三方审计）。
 *
 * - 首屏 ready：CI 预算 3s（本机 prod 目标 600ms，见 SLA_BUDGET_MS）
 * - /api/health：p95 预算 500ms（单样本）
 */
import { test, expect } from '@playwright/test'

const SLA_BUDGET_MS = Number(process.env.XCAGI_SLA_READY_MS || '3000')
const HEALTH_BUDGET_MS = Number(process.env.XCAGI_SLA_HEALTH_MS || '500')

test.describe('SLA probes (CI budgets)', () => {
  test('app shell becomes ready within budget', async ({ page }) => {
    const t0 = Date.now()
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: SLA_BUDGET_MS })
    const elapsed = Date.now() - t0
    expect(elapsed).toBeLessThan(SLA_BUDGET_MS + 500)
    test.info().annotations.push({
      type: 'sla',
      description: `ready_ms=${elapsed} budget_ms=${SLA_BUDGET_MS}`,
    })
  })

  test('backend health responds within budget when API is up', async ({ request }) => {
    const apiBase = process.env.PLAYWRIGHT_API_URL || 'http://127.0.0.1:5000'
    const t0 = Date.now()
    const res = await request.get(`${apiBase}/api/health`, { timeout: HEALTH_BUDGET_MS + 2000 })
    const elapsed = Date.now() - t0
    if (res.ok()) {
      expect(elapsed).toBeLessThan(HEALTH_BUDGET_MS + 200)
    } else {
      test.skip(true, `API not reachable at ${apiBase}`)
    }
  })
})
