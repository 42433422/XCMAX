import { test, expect } from '@playwright/test'
import { installStartupReadinessMocks } from '../e2e/startup-readiness-fixture'
import { capture, isolate } from './capture'

for (const [width, height] of [[1440, 900], [1024, 768]]) {
  test('desktop shell ' + width, async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height })
    await isolate(page, baseURL!)
    await installStartupReadinessMocks(page)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 30000 })
    await expect(page.getByTestId('startup-readiness')).toHaveCount(0)
    const composer = page.locator('#messageInput')
    await expect(composer).toBeVisible()
    await capture(page, 'shell-empty-' + width)
    await composer.fill('请整理本周订单与库存')
    await expect(composer).toHaveValue('请整理本周订单与库存')
    await capture(page, 'shell-draft-' + width)
    await page.getByRole('button', { name: '系统设置', exact: true }).first().click()
    await expect(page.locator('#view-settings')).toBeVisible()
    await capture(page, 'shell-settings-' + width)
  })
}
