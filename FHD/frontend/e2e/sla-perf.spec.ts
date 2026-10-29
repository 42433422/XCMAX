import { test, expect, type TestInfo } from '@playwright/test'
import { installE2eShellMocks, isFullStack, loginBrowserSession } from './helpers'
import { assertWithinBudget, latencyPercentile, positiveBudget } from './performance-budget'

const readyMs = positiveBudget(process.env.XCAGI_SLA_READY_MS, 3000)
const healthMs = positiveBudget(process.env.XCAGI_SLA_HEALTH_MS, 500)
const healthUrl = `${(process.env.E2E_API_BASE_URL || process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5001').replace(/\/$/, '')}/api/health`

async function record(testInfo: TestInfo, data: Record<string, unknown>): Promise<void> {
  await testInfo.attach('performance-measurements', {
    body: JSON.stringify({ source_sha: process.env.GITHUB_SHA || process.env.SOURCE_SHA || null, ...data }, null, 2),
    contentType: 'application/json',
  })
}

test.describe('Measured performance budgets', () => {
  test('home shell ready within XCAGI_SLA_READY_MS', async ({ page }, testInfo) => {
    if (isFullStack()) await loginBrowserSession(page)
    else await installE2eShellMocks(page)
    const started = performance.now()
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 30_000 })
    const elapsed = performance.now() - started
    await record(testInfo, {
      scope: isFullStack() ? 'authenticated shell with real API' : 'isolated UI shell; authentication responses mocked',
      samples_ms: [elapsed], budget_ms: readyMs,
    })
    assertWithinBudget(elapsed, readyMs, 'home shell ready')
  })

  test('/api/health responds within XCAGI_SLA_HEALTH_MS', async ({ request }, testInfo) => {
    const started = performance.now()
    const response = await request.get(healthUrl, { timeout: 15_000 })
    const elapsed = performance.now() - started
    await record(testInfo, { scope: 'real HTTP health request', samples_ms: [elapsed], budget_ms: healthMs })
    expect(response.status(), await response.text()).toBe(200)
    expect(response.headers()['content-type']).toContain('application/json')
    assertWithinBudget(elapsed, healthMs, 'health request')
  })

  test('health P95/P99 derive from real HTTP samples', async ({ request }, testInfo) => {
    const samples: number[] = []
    for (let i = 0; i < 30; i += 1) {
      const started = performance.now()
      const response = await request.get(healthUrl, { timeout: 15_000 })
      samples.push(performance.now() - started)
      expect(response.status(), await response.text()).toBe(200)
      expect(response.headers()['content-type']).toContain('application/json')
    }
    const p95 = latencyPercentile(samples, 95)
    const p99 = latencyPercentile(samples, 99)
    await record(testInfo, {
      scope: '30 sequential HTTP requests; local regression, not production SLO',
      samples_ms: samples, p95_ms: p95, p99_ms: p99, budget_ms: healthMs,
    })
    assertWithinBudget(p95, healthMs, 'health P95')
    assertWithinBudget(p99, healthMs, 'health P99')
  })
})
