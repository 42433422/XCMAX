import { expect, test } from '@playwright/test'

// 并行 worker 同时打同一 Vite dev 实例时易出现首屏/路由竞态（如未清 token 的误判）；本文件串行更稳。
test.describe.configure({ mode: 'serial' })

async function stubCommonApis(page: import('@playwright/test').Page) {
  await page.route('**/*', async (route) => {
    const { pathname } = new URL(route.request().url())
    if (pathname === '/api/auth/me') {
      await route.fulfill({ json: { id: 1, username: 'tester', is_admin: false } })
      return
    }
    if (pathname === '/api/wallet/balance') {
      await route.fulfill({ json: { balance: 0 } })
      return
    }
    if (pathname === '/api/notifications') {
      await route.fulfill({ json: { items: [], unread_count: 0 } })
      return
    }
    if (pathname === '/api/payment/plans') {
      await route.fulfill({
        json: {
          plans: [
            {
              id: 'basic',
              name: '基础版',
              price: 9.9,
              description: '适合试用',
              features: ['1 个员工', '基础工作台'],
            },
          ],
        },
      })
      return
    }
    if (pathname === '/api/payment/sign-checkout') {
      await route.fulfill({
        json: {
          plan_id: 'basic',
          item_id: 0,
          total_amount: 9.9,
          subject: '基础版',
          wallet_recharge: false,
          request_id: 'req-e2e',
          timestamp: 1710000000,
          signature: 'sig-e2e',
        },
      })
      return
    }
    if (pathname === '/api/payment/checkout') {
      await route.fulfill({ json: { ok: true, type: 'precreate', order_id: 'order-e2e' } })
      return
    }
    if (pathname.startsWith('/api/payment/query/')) {
      await route.fulfill({
        json: {
          out_trade_no: 'order-e2e',
          subject: '基础版',
          total_amount: 9.9,
          status: 'paid',
          trade_no: 'trade-e2e',
          created_at: '2026-01-02T03:04:05Z',
          paid_at: '2026-01-02T03:05:05Z',
          refund_status: 'none',
          refunded_amount: 0,
        },
      })
      return
    }
    if (pathname === '/api/employees/') {
      await route.fulfill({ json: [] })
      return
    }
    if (pathname === '/api/workflow/employee-eligible') {
      await route.fulfill({ json: { workflows: [], all_workflows: [] } })
      return
    }
    if (pathname.startsWith('/api/')) {
      await route.fulfill({ json: { items: [], ok: true, workflows: [], executions: [] } })
      return
    }
    if (pathname.startsWith('/v1/')) {
      await route.fulfill({ json: { items: [] } })
      return
    }
    await route.fallback()
  })
}

test('protected pages redirect anonymous users to login', async ({ page }) => {
  await page.goto('/wallet')

  await expect(page).toHaveURL(/\/login\?redirect=.*wallet/)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
})

test('top navigation stays inside the market router', async ({ page }) => {
  await stubCommonApis(page)
  await page.addInitScript(() => localStorage.setItem('modstore_token', 'token-e2e'))

  await page.goto('/plans')

  await expect(page.getByRole('link', { name: 'XC AGI' })).toHaveAttribute('href', /\/workbench\/home$/)
  await expect(page.getByRole('link', { name: '工作台' })).toHaveAttribute('href', /\/workbench\/home$/)
  await expect(page.getByRole('link', { name: '会员' })).toHaveAttribute('href', /\/plans$/)
  await expect(page.getByRole('link', { name: 'AI 市场' })).toHaveAttribute('href', /\/ai-store$/)
  await expect(page.getByRole('link', { name: '钱包' })).toHaveAttribute('href', /\/wallet$/)
})

test('plan purchase creates a checkout order for authenticated users', async ({ page }) => {
  await stubCommonApis(page)
  await page.addInitScript(() => localStorage.setItem('modstore_token', 'token-e2e'))

  await page.goto('/plans')
  await expect(page.getByRole('heading', { name: '基础版' })).toBeVisible()
  await page.locator('.plan-card .btn-primary').click()

  await expect(page).toHaveURL(/\/checkout\/order-e2e/)
})

test('order detail renders payment and refund state', async ({ page }) => {
  await stubCommonApis(page)
  await page.addInitScript(() => localStorage.setItem('modstore_token', 'token-e2e'))

  await page.goto('/order/order-e2e')

  await expect(page.getByText('order-e2e')).toBeVisible()
  await expect(page.getByText('已支付')).toBeVisible()
  await expect(page.getByText('无退款')).toBeVisible()
})

test('workbench shell target tabs switch between employee, workflow, mod and skill surfaces', async ({ page }) => {
  await stubCommonApis(page)
  await page.addInitScript(() => {
    localStorage.setItem('modstore_token', 'token-e2e')
  })

  // Navigate to the new AI-native shell (employee target)
  await page.goto('/workbench/shell/employee')
  // Shell renders with employee target tab active
  await expect(page).toHaveURL(/\/workbench\/shell\/employee/)

  // Legacy unified redirect still works
  await page.goto('/workbench/unified')
  await expect(page).toHaveURL(/\/workbench\/shell/)

  // /workbench/home 仍渲染原主界面
  await page.goto('/workbench/home')
  await expect(page).toHaveURL(/\/workbench\/home/)
})

test('unknown routes render the not found page', async ({ page }) => {
  await page.goto('/does-not-exist')

  await expect(page.getByRole('heading', { name: '404' })).toBeVisible()
  await expect(page.getByText('抱歉，您访问的页面不存在')).toBeVisible()
})

test('wallet shows stub balance for logged-in users', async ({ page }) => {
  await stubCommonApis(page)
  await page.addInitScript(() => localStorage.setItem('modstore_token', 'token-e2e'))

  await page.goto('/wallet')

  await expect(page.getByRole('heading', { name: '资金与记录' })).toBeVisible()
  await expect(page.getByText('¥0.00')).toBeVisible()
})

test('customer service page renders hero for logged-in users', async ({ page }) => {
  await stubCommonApis(page)
  await page.addInitScript(() => localStorage.setItem('modstore_token', 'token-e2e'))

  await page.goto('/customer-service')

  await expect(page.getByRole('heading', { level: 1, name: '自动受理、审核、执行与追踪' })).toBeVisible()
})
