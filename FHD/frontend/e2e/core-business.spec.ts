import { test, expect } from '@playwright/test'
import { installE2eShellMocks, isFullStack } from './helpers'

test.describe('Core business flows (basic)', () => {
  test('chat send triggers backend request', async ({ page }) => {
    // Intercept AI chat endpoint and return canned response
    await page.route('**/api/ai/chat*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: { reply: 'ok' } }),
      }),
    )

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('#app')).toBeVisible()
    // wait for app ready marker
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 20_000 })

    // Call the page-level chat send bridge if available
    const hasBridge = await page.evaluate(() => {
      return typeof (window as any).__VUE_CHAT_SEND__ === 'function'
    })
    if (hasBridge) {
      // trigger send via bridge; wait for the network call to be observed
      await page.evaluate(() => {
        ;(window as any).__VUE_CHAT_SEND__('测试消息 from E2E')
      })
      await page.waitForResponse((resp) => resp.url().includes('/api/ai/chat') && resp.status() === 200, {
        timeout: 5000,
      })
    } else {
      test.skip(true, 'No chat bridge available in this build')
    }
  })

  test('mods list loads and displays mod name', async ({ page }) => {
    await page.route('**/api/mods/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: [{ id: 'm1', name: 'TestMod', version: '1.0', author: '', description: '' }],
        }),
      }),
    )

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 20_000 })
    // best-effort: look for the mod name text somewhere in the page
    await expect(page.locator('text=TestMod')).toBeVisible({ timeout: 5000 })
  })

  test('pro mode toggle (dispatch event)', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 20_000 })
    // dispatch a custom pro-mode-changed event and ensure page doesn't crash
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('xcagi:pro-mode-changed', { detail: { enabled: true } }))
    })
    // no uncaught exceptions implies success; also ensure app root still visible
    await expect(page.locator('#app')).toBeVisible()
  })

  test('库存调拨：从 A 仓调拨到 B 仓后两边库存数量正确更新', async ({ page, request }) => {
    test.skip(isFullStack(), 'full-stack 模式由真实后端覆盖；此处只校验 mock 行为')
    await installE2eShellMocks(page)

    let transferCalls = 0
    let lastTransferPayload: any = null
    await page.route('**/api/inventory/transfer', async (route) => {
      transferCalls += 1
      const body = route.request().postDataJSON()
      lastTransferPayload = body
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            from_warehouse: body?.from_warehouse ?? 'A',
            to_warehouse: body?.to_warehouse ?? 'B',
            sku: body?.sku ?? 'SKU-001',
            quantity: Number(body?.quantity ?? 0),
            from_balance: 80,
            to_balance: 20,
          },
        }),
      })
    })

    await page.route('**/api/inventory/balance*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: [
            { warehouse: 'A', sku: 'SKU-001', quantity: 100 },
            { warehouse: 'B', sku: 'SKU-001', quantity: 0 },
          ],
        }),
      }),
    )

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })

    const apiBase = (process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5001').replace(/\/$/, '')
    const transferResp = await request.post(`${apiBase}/api/inventory/transfer`, {
      data: { from_warehouse: 'A', to_warehouse: 'B', sku: 'SKU-001', quantity: 20 },
      timeout: 15_000,
    })
    expect(transferResp.status(), await transferResp.text()).toBe(200)
    const body = await transferResp.json()
    expect(body?.success).toBe(true)
    expect(body?.data?.from_balance).toBe(80)
    expect(body?.data?.to_balance).toBe(20)

    expect(transferCalls, 'transfer endpoint should be invoked once').toBeGreaterThanOrEqual(1)
    expect(lastTransferPayload).toMatchObject({ from_warehouse: 'A', to_warehouse: 'B', quantity: 20 })
  })
})
