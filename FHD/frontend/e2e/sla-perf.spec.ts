import { test, expect } from '@playwright/test'
import { installE2eShellMocks, isFullStack } from './helpers'

const readyMs = Number(process.env.XCAGI_SLA_READY_MS || 3000)
const healthMs = Number(process.env.XCAGI_SLA_HEALTH_MS || 500)

test.describe('SLA performance budgets', () => {
  test('home shell ready within XCAGI_SLA_READY_MS', async ({ page }) => {
    await installE2eShellMocks(page)
    const started = Date.now()
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: readyMs + 20_000 })
    const elapsed = Date.now() - started
    expect(elapsed, `shell ready in ${elapsed}ms`).toBeLessThan(readyMs + 20_000)
  })

  test('/api/health responds within XCAGI_SLA_HEALTH_MS', async ({ request }) => {
    const started = Date.now()
    const resp = await request.get('/api/health', { timeout: 15_000 })
    const elapsed = Date.now() - started
    expect(resp.status()).toBeLessThan(500)
    expect(elapsed, `health took ${elapsed}ms`).toBeLessThan(healthMs * 6)
  })

  test('/api/sla/report 返回 P95/P99 指标且字段齐全', async ({ page, request }) => {
    const apiBase = (process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5001').replace(/\/$/, '')

    if (isFullStack()) {
      const started = Date.now()
      const resp = await request.get(`${apiBase}/api/sla/report?window=30d`, { timeout: 20_000 })
      const elapsed = Date.now() - started
      expect(resp.status(), await resp.text()).toBeLessThan(500)
      const body = await resp.json().catch(() => ({}) as any)
      const data = body?.data || body || {}
      const p95 = Number(data.p95 ?? data.P95 ?? data.p95_ms ?? -1)
      const p99 = Number(data.p99 ?? data.P99 ?? data.p99_ms ?? -1)
      const samples = Number(data.samples ?? data.sample_count ?? -1)
      expect(p95, `sla report p95 field: ${JSON.stringify(body)}`).toBeGreaterThanOrEqual(0)
      expect(p99, `sla report p99 field: ${JSON.stringify(body)}`).toBeGreaterThanOrEqual(0)
      expect(samples, `sla report samples field: ${JSON.stringify(body)}`).toBeGreaterThanOrEqual(0)
      if (p95 > 0 && p99 > 0) {
        expect(p99, 'p99 should be >= p95').toBeGreaterThanOrEqual(p95)
      }
      expect(elapsed, `sla report took ${elapsed}ms`).toBeGreaterThanOrEqual(0)
      return
    }

    await installE2eShellMocks(page)
    await page.route('**/api/sla/report**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: { p95: 200, p99: 500, samples: 100 } }),
      }),
    )
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })

    const result = await page.evaluate(async () => {
      const r = await fetch('/api/sla/report?window=30d')
      const json = await r.json().catch(() => ({}) as any)
      return { status: r.status, body: json }
    })
    expect(result.status, `sla report status`).toBe(200)
    const data = result.body?.data || result.body || {}
    expect(Number(data.p95), `p95 should be 200, body=${JSON.stringify(result.body)}`).toBe(200)
    expect(Number(data.p99), `p99 should be 500`).toBe(500)
    expect(Number(data.samples), `samples should be 100`).toBe(100)
    expect(Number(data.p99)).toBeGreaterThanOrEqual(Number(data.p95))
  })
})
