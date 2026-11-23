import { test, expect, type TestInfo } from '@playwright/test'
import { installE2eShellMocks, isFullStack, loginBrowserSession } from './helpers'
import { assertWithinBudget, latencyPercentile, positiveBudget } from './performance-budget'

const readyMs = positiveBudget(process.env.XCAGI_SLA_READY_MS, 3000)
const healthMs = positiveBudget(process.env.XCAGI_SLA_HEALTH_MS, 500)
const sourceSha = process.env.GITHUB_SHA || process.env.SOURCE_SHA || null
const healthUrl = `${(process.env.E2E_API_BASE_URL || process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5001').replace(/\/$/, '')}/api/health`

async function record(testInfo: TestInfo, data: Record<string, unknown>): Promise<void> {
  await testInfo.attach('performance-measurements', {
    body: JSON.stringify({ source_sha: sourceSha, ...data }, null, 2),
    contentType: 'application/json',
  })
}

test.describe('Measured performance budgets', () => {
  test('home shell ready within XCAGI_SLA_READY_MS', async ({ page }, testInfo) => {
    if (isFullStack()) await loginBrowserSession(page)
    else await installE2eShellMocks(page)
    const rendererErrors: string[] = []
    const failedReads: Array<{ path: string; status: number }> = []
    page.on('pageerror', error => { if (rendererErrors.length < 20) rendererErrors.push(error.message) })
    page.on('console', message => {
      if (message.type() === 'error' && message.text().startsWith('[Vue]') && rendererErrors.length < 20) {
        rendererErrors.push(message.text())
      }
    })
    page.on('response', response => {
      const path = new URL(response.url()).pathname
      if (response.status() >= 400 && path.startsWith('/api/') && failedReads.length < 20) {
        failedReads.push({ path, status: response.status() })
      }
    })
    const started = performance.now()
    let elapsed: number
    try {
      await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
      await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 30_000 })
      // Public login routes also have an is-ready shell. Only the usable home
      // workspace can supply this measurement.
      await expect(page).toHaveURL(url => url.pathname === '/')
      await expect(page.getByTestId('startup-workspace')).not.toHaveAttribute('inert')
      await page.locator('#messageInput').fill('SLA readiness probe')
      await expect(page.locator('#messageInput')).toHaveValue('SLA readiness probe')
      elapsed = performance.now() - started
      expect(rendererErrors, 'Vue updates must complete without a renderer failure').toEqual([])
      if (!isFullStack()) expect(failedReads, 'Synthetic account startup reads must stay isolated').toEqual([])
    } finally {
      const state = await page.evaluate(() => ({
        path: location.pathname,
        mounted: document.getElementById('app')?.dataset.startupMounted,
        ready: document.getElementById('app')?.dataset.startupReady,
        shell: document.querySelector('.app-shell')?.className,
        startupState: document.querySelector('[data-testid="startup-readiness"]')?.getAttribute('data-state'),
      })).catch(() => ({ unavailable: true }))
      await testInfo.attach('ui-startup-diagnostics', {
        body: JSON.stringify({ state, rendererErrors, failedReads }, null, 2),
        contentType: 'application/json',
      })
    }
    const buildSourceSha = await page.locator('head').evaluate((head) =>
      head.querySelector('meta[name="xcmax-release-git-sha"]')?.getAttribute('content') ?? null,
    )
    await record(testInfo, {
      scope: isFullStack() ? 'authenticated shell with real API' : 'isolated UI shell with synthetic account and startup reads',
      samples_ms: [elapsed], budget_ms: readyMs, build_source_sha: buildSourceSha,
    })
    expect(sourceSha, 'A source commit is required for the measured UI build').toMatch(/^[0-9a-f]{40}$/)
    expect(buildSourceSha, 'The served UI must match the tested source commit').toBe(sourceSha)
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
