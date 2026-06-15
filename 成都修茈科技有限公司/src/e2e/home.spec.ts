import { expect, test } from '@playwright/test'

test('首页可加载，标题包含 XC AGI', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/XCAGI/i)
  await expect(page.getByRole('link', { name: /AI 市场/ }).first()).toBeVisible()
})

test('官网首页可见核心栏目', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: '产品中心' }).first()).toBeVisible()
  await expect(page.getByRole('link', { name: '解决方案' }).first()).toBeVisible()
  await expect(page.getByRole('link', { name: '联系我们' }).first()).toBeVisible()
})

test('AI 市场入口指向 /market/', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: /AI 市场/ }).first()).toHaveAttribute('href', '/market/')
})
