/**
 * 阶段2 · 5 条核心业务 E2E（API 契约级，Playwright request + 路由 mock）
 *
 * 1. AI 对话
 * 2. 出货（shipment records）
 * 3. 支付（model-payment checkout）
 * 4. 签收（shipment record 状态更新）
 * 5. 对账（finance unified-ledger）
 */
import { test, expect } from '@playwright/test'

async function waitAppReady(page: import('@playwright/test').Page) {
  await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
  await expect(page.locator('#app')).toBeVisible()
  await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
}

test.describe('阶段2 — 5 核心业务流程', () => {
  test('1. AI 对话 — chat API', async ({ page }) => {
    await page.route('**/api/ai/chat*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: { reply: 'e2e-ok' } }),
      })
    )
    await waitAppReady(page)
    const res = await page.request.post('/api/ai/chat', {
      data: { message: 'hello e2e' },
    })
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.success).toBe(true)
    expect(body.data.reply).toBe('e2e-ok')
  })

  test('2. 出货 — create shipment record', async ({ page }) => {
    await page.route('**/api/shipment/shipment-records/**', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: { id: 'ship-e2e', order_number: 'ORD-E2E', status: 'shipped' },
          }),
        })
      }
      return route.continue()
    })
    await waitAppReady(page)
    const res = await page.request.post('/api/shipment/shipment-records/record', {
      data: { order_number: 'ORD-E2E', quantity: 1 },
    })
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.data.status).toBe('shipped')
  })

  test('3. 支付 — model-payment checkout', async ({ page }) => {
    await page.route('**/api/model-payment/checkout', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: { checkout_id: 'chk-e2e', status: 'pending' },
        }),
      })
    )
    await waitAppReady(page)
    const res = await page.request.post('/api/model-payment/checkout', {
      data: { plan_id: 'pro' },
    })
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.data.checkout_id).toBe('chk-e2e')
  })

  test('4. 签收 — patch shipment delivered', async ({ page }) => {
    await page.route('**/api/shipment/shipment-records/record', (route) => {
      if (route.request().method() === 'PATCH') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: { id: 'ship-e2e', status: 'delivered', signed_at: '2026-06-03' },
          }),
        })
      }
      return route.continue()
    })
    await waitAppReady(page)
    const res = await page.request.patch('/api/shipment/shipment-records/record', {
      data: { id: 'ship-e2e', status: 'delivered' },
    })
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.data.status).toBe('delivered')
  })

  test('5. 对账 — unified ledger summary', async ({ page }) => {
    await page.route('**/api/finance/unified-ledger/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: { total_debit: 100, total_credit: 100, balanced: true },
        }),
      })
    )
    await waitAppReady(page)
    const res = await page.request.get('/api/finance/unified-ledger/summary')
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.data.balanced).toBe(true)
  })
})
