import { test, expect } from '@playwright/test'
import { captureEvidence, E2E_PASSWORD, E2E_USER, isFullStack } from '../e2e/helpers'

// e2e-full.sh runs this against its fresh data directory before ERP fixtures bind an industry.
test('fresh enterprise form login requires industry selection with the baseline installed', async ({ page }) => {
  expect(isFullStack(), 'This case requires the isolated e2e-full.sh backend').toBe(true)
  await page.goto('/login?redirect=%2Forders', { waitUntil: 'domcontentloaded', timeout: 30_000 })
  await page.locator('#lv-username').fill(E2E_USER)
  await page.locator('#lv-password').fill(E2E_PASSWORD)
  const loginResponsePromise = page.waitForResponse(
    (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/auth/login',
    { timeout: 45_000 },
  )
  await page.locator('.login-submit').click()
  const loginResponse = await loginResponsePromise
  expect(loginResponse.status(), await loginResponse.text()).toBe(200)
  expect(await loginResponse.json()).toMatchObject({ success: true })
  await expect(page).toHaveURL(
    (url) => url.pathname === '/onboarding' && url.searchParams.get('step') === 'industry',
    { timeout: 45_000 },
  )
  await expect(page.getByRole('heading', { name: '先定行业', exact: true })).toBeVisible()
  await expect(page.getByRole('listbox', { name: '可选行业' })).toBeVisible()

  const prefsResponse = await page.request.get('/api/workspace/prefs')
  expect(prefsResponse.ok(), await prefsResponse.text()).toBe(true)
  const prefs = await prefsResponse.json()
  expect(prefs.success).toBe(true)
  expect(typeof prefs.owner_id).toBe('string')
  expect(prefs.owner_id.trim()).not.toBe('')
  expect(prefs.data.selected_industry_id || '').toBe('')
  expect(prefs.data.product_flow_completed).not.toBe(true)

  const catalogResponse = await page.request.get('/api/platform-shell/onboarding-industries')
  expect(catalogResponse.ok(), await catalogResponse.text()).toBe(true)
  const catalogBody = await catalogResponse.json()
  expect(catalogBody.success).toBe(true)
  const catalog = catalogBody.data || catalogBody
  expect(catalog.owner_id).toBe(prefs.owner_id)
  expect(catalog.selected_industry_id || '').toBe('')
  const baselineResponse = await page.request.get('/api/platform-shell/industry-baseline', {
    params: { industry_id: '涂料' },
  })
  expect(baselineResponse.ok(), await baselineResponse.text()).toBe(true)
  const baselineBody = await baselineResponse.json()
  expect(baselineBody.success).toBe(true)
  expect((baselineBody.data || baselineBody).baseline_ready).toBe(true)
  await captureEvidence(page, '00-first-login-industry.png')
})
