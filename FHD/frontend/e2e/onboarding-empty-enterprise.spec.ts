import { test, expect, type Page } from '@playwright/test'
import { csrfHeaders, E2E_ACCOUNT_KIND, E2E_PASSWORD, E2E_USER, isFullStack } from './helpers'

// This writes the test account's company and industry. Use a fresh, isolated
// desktop database and a dedicated account; never a customer's working account.
test.describe('three-step enterprise onboarding @onboarding_e2e', () => {
  test.skip(!isFullStack() || process.env.E2E_ISOLATED_ONBOARDING !== '1', 'requires an explicitly isolated full-stack onboarding fixture')

  async function login(page: Page) {
    const headers = await csrfHeaders(page.request)
    const response = await page.request.post('/api/auth/login', {
      headers,
      data: { username: E2E_USER, password: E2E_PASSWORD, account_kind: E2E_ACCOUNT_KIND },
    })
    expect(response.ok()).toBe(true)
    expect((await response.json()).success).toBe(true)
  }

  test('saves company and industry, completes three steps, and keeps chat first after a new login', async ({ page }) => {
    test.setTimeout(120_000)
    const company = process.env.E2E_ONBOARDING_COMPANY || 'XC 入门回归测试公司'
    const seedRequests: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/platform-shell/onboarding/seed-demo') {
        seedRequests.push(request.url())
      }
    })
    await login(page)
    await page.goto('/')
    await expect(page.getByLabel('公司或团队名称')).toBeVisible()
    await expect(page.getByLabel('设置流程')).toContainText('公司')
    await expect(page.getByLabel('设置流程')).not.toContainText('演示数据')
    await page.getByLabel('公司或团队名称').fill(company)
    await page.getByRole('button', { name: /让 XC 认识我的公司/ }).click()
    await expect(page.getByRole('listbox', { name: '可选行业' })).toBeVisible()
    await page.getByLabel('搜索或描述行业').fill('涂料')
    await page.getByRole('option', { name: /^涂料/ }).first().click()
    await page.getByRole('button', { name: '生成我的配置方案' }).click()
    await expect(page.getByRole('heading', { name: `${company}的配置方案` })).toBeVisible()
    await page.getByRole('button', { name: `进入${company}工作空间` }).click()
    await expect(page).not.toHaveURL(/\/onboarding/)
    await expect(page.locator('button.menu-item[data-view]').first()).toContainText('智能对话')
    expect(seedRequests).toEqual([])

    const me = await page.request.get('/api/auth/me')
    expect(me.ok()).toBe(true)
    expect((await me.json()).data.tenant_name).toBe(company)
    const logout = await page.request.post('/api/auth/logout', { headers: await csrfHeaders(page.request) })
    expect(logout.ok()).toBe(true)
    await login(page)
    await page.reload()
    await expect(page).not.toHaveURL(/\/onboarding/)
    await expect(page.locator('button.menu-item[data-view]').first()).toContainText('智能对话')
    const restored = await page.request.get('/api/auth/me')
    expect((await restored.json()).data.tenant_name).toBe(company)
    expect(seedRequests).toEqual([])
  })
})
