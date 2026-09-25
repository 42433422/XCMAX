import { expect, test } from '@playwright/test'

test('首页按客户主线呈现品牌、导航与体验入口', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/XCAGI/i)
  await expect(page.getByRole('heading', { name: /把重复业务交给 XCAGI/ })).toBeVisible()
  for (const label of ['产品', '解决方案', '客户案例', '价格', '下载', '验证中心', '联系我们']) await expect(page.getByRole('link', { name: label, exact: true }).first()).toBeVisible()
  await Promise.all([
    expect(page.getByRole('link', { name: '99 元体验 30 天', exact: true }).first()).toHaveAttribute('href', /\/market\/account-plans\?plan=saas-trial-30/),
    expect(page.getByRole('link', { name: '查看真实案例', exact: true }).first()).toHaveAttribute('href', '/cases.html'),
  ])
})
