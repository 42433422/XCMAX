import { test, expect } from '@playwright/test'

test.describe('onboarding empty enterprise @onboarding_e2e', () => {
  test.skip(true, 'requires full-stack E2E backend; run with E2E_FULL_STACK=1')

  test('register → industry → host-pack → seed → ai demo', async ({ page }) => {
    await page.goto('/register')
    await page.getByRole('button', { name: /注册|创建/i }).click()
    await page.goto('/onboarding?step=industry')
    await expect(page.getByText(/行业定型/)).toBeVisible()
    await page.goto('/onboarding?step=seed-demo')
    await expect(page.getByText(/首笔业务数据/)).toBeVisible()
    await page.getByRole('button', { name: /写入演示数据|下一步/i }).click()
    await page.goto('/onboarding?step=first-ai-task')
    await expect(page.getByText(/AI 读写验收/)).toBeVisible()
  })
})
