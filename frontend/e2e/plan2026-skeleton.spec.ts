/**
 * plan-2026-06 T30/T31：5 条关键链路骨架（登录 / 产品 / 对话 / 订单 / 打印）
 *
 * 默认 skip：需 E2E_FULL_STACK=1 且 API :5000 + Vite :5001 + 种子账号。
 * CI 会收集本文件但用例在无全栈时自动跳过，不阻塞流水线。
 */
import { test, expect } from '@playwright/test'

const needsFullStack = () => !process.env.E2E_FULL_STACK

async function waitShell(page: import('@playwright/test').Page) {
  await expect(page.locator('#app')).toBeVisible()
  await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
}

test.describe('Plan 2026-06 — login', () => {
  test.skip(needsFullStack, 'Set E2E_FULL_STACK=1 with API :5000, Vite :5001, seeded credentials')

  test('login → ready shell', async ({ page }) => {
    await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    // TODO: E2E_USER / E2E_PASSWORD from env
    await waitShell(page)
  })
})

test.describe('Plan 2026-06 — product', () => {
  test.skip(needsFullStack, 'Set E2E_FULL_STACK=1')

  test('create product → visible in list', async ({ page }) => {
    await page.goto('/products', { waitUntil: 'domcontentloaded' })
    await waitShell(page)
    // TODO: open create dialog, submit SKU, assert table row
  })
})

test.describe('Plan 2026-06 — chat / assistant', () => {
  test.skip(needsFullStack, 'Set E2E_FULL_STACK=1')

  test('open assistant float → panel visible', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await waitShell(page)
    await page.locator('.assistant-float-toggle').click()
    await expect(page.locator('#xcagi-assistant-float-panel')).toBeVisible()
    // TODO: send message, expect assistant reply stub or SSE chunk
  })
})

test.describe('Plan 2026-06 — order', () => {
  test.skip(needsFullStack, 'Set E2E_FULL_STACK=1')

  test('create order → detail page', async ({ page }) => {
    await page.goto('/orders', { waitUntil: 'domcontentloaded' })
    await waitShell(page)
    // TODO: pick customer + product, submit, expect /orders/:id
  })
})

test.describe('Plan 2026-06 — print', () => {
  test.skip(needsFullStack, 'Set E2E_FULL_STACK=1')

  test('order detail → print preview', async ({ page }) => {
    await page.goto('/orders', { waitUntil: 'domcontentloaded' })
    await waitShell(page)
    // TODO: open first order, trigger print, expect PDF/image preview region
  })
})
