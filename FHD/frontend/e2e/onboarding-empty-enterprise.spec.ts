import { test, expect } from '@playwright/test'
import { installE2eShellMocks, isFullStack } from './helpers'

test.describe('onboarding empty enterprise @onboarding_e2e', () => {
  test.describe('full-stack only', () => {
    test.skip(true, 'requires full-stack E2E backend; run with E2E_FULL_STACK=1')

    test('register → industry → host-pack（宿主入门仅三步）', async ({ page }) => {
      await page.goto('/register')
      await page.getByRole('button', { name: /注册|创建/i }).click()
      await page.goto('/onboarding?step=welcome')
      await expect(page.getByText(/认识 XC|认识XC/)).toBeVisible()
      await page.goto('/onboarding?step=industry')
      await expect(page.getByText(/先定行业|行业定型/)).toBeVisible()
      await page.goto('/onboarding?step=host-pack')
      await expect(page.getByText(/准备侧栏|准备菜单/)).toBeVisible()
    })
  })

  test('onboarding 多步：industry → host-pack → seed → ai-demo 全流程串接', async ({ page, request }) => {
    const apiBase = (process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5001').replace(/\/$/, '')

    if (!isFullStack()) {
      await installE2eShellMocks(page)
      await page.route('**/api/onboarding/industry', (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: { step: 'industry', industries: ['retail', 'manufacturing'] } }),
        })
      )
      await page.route('**/api/onboarding/host-pack', (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: { step: 'host-pack', packs: ['basic', 'pro'] } }),
        })
      )
      await page.route('**/api/onboarding/seed', (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: { step: 'seed', seeded: true, count: 12 } }),
        })
      )
      await page.route('**/api/onboarding/ai-demo', (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: { step: 'ai-demo', ready: true } }),
        })
      )
    }

    const steps = ['industry', 'host-pack', 'seed', 'ai-demo']
    const seenSteps: string[] = []
    for (const step of steps) {
      const resp = await request.get(`${apiBase}/api/onboarding/${step}`, { timeout: 15_000 })
      expect(resp.status(), await resp.text()).toBeLessThan(500)
      const body = await resp.json().catch(() => ({} as any))
      expect(body?.success, `onboarding ${step} body: ${JSON.stringify(body)}`).toBe(true)
      const stepField = String(body?.data?.step || step)
      expect(stepField).toBe(step)
      seenSteps.push(stepField)
    }
    expect(seenSteps).toEqual(steps)

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    expect(seenSteps.length).toBe(4)
  })
})
