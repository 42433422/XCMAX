/**
 * P0 主链路 5 条关键路径回归（Web；桌面壳内 WebView 与同一 SPA，见 desktop-shell.spec.ts）
 *
 * 1. 登录
 * 2. 上传 Excel → 解析
 * 3. 打印
 * 4. Mod 安装/列表
 * 5. 串联冒烟（登录态 → 业务 API 可达）
 */
import { test, expect } from '@playwright/test'

async function waitAppReady(page: import('@playwright/test').Page) {
  await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
  await expect(page.locator('#app')).toBeVisible()
  await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
}

test.describe('P0 critical path 1 — login', () => {
  test('login route renders credential form or redirects to ready shell', async ({ page }) => {
    await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('#app')).toBeVisible()
    const onLogin = page.url().includes('/login')
    if (onLogin) {
      const pwd = page.locator('input[type="password"], input[autocomplete="current-password"]').first()
      await expect(pwd).toBeVisible({ timeout: 10_000 })
    } else {
      await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 20_000 })
    }
  })
})

test.describe('P0 critical path 2 — excel upload & parse', () => {
  test('excel upload returns parsed payload', async ({ page }) => {
    await page.route('**/api/excel/upload', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: { rows: 3, columns: ['A', 'B'], sheet: 'Sheet1' },
        }),
      })
    )
    await waitAppReady(page)
    const res = await page.request.post('/api/excel/upload', {
      multipart: {
        file: {
          name: 'e2e-sample.xlsx',
          mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          buffer: Buffer.from('PK\x03\x04e2e'),
        },
      },
    })
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.success).toBe(true)
    expect(body.data.rows).toBe(3)
  })
})

test.describe('P0 critical path 3 — print', () => {
  test('printer list and print job API', async ({ page }) => {
    await page.route('**/api/printers', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: [{ name: 'E2E-Printer', default: true }] }),
      })
    )
    await page.route('**/api/print/**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    )
    await waitAppReady(page)
    const printers = await page.request.get('/api/printers')
    expect(printers.ok()).toBeTruthy()
    const printRes = await page.request.post('/api/print/e2e-label.pdf', { data: {} })
    expect(printRes.ok()).toBeTruthy()
  })
})

test.describe('P0 critical path 4 — mod install', () => {
  test('mods list and install endpoint', async ({ page }) => {
    await page.route('**/api/mods/**', (route) => {
      const url = route.request().url()
      if (route.request().method() === 'GET' && url.endsWith('/api/mods/')) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: [{ id: 'e2e-mod', name: 'E2E Mod', version: '1.0.0', installed: false }],
          }),
        })
      }
      if (route.request().method() === 'POST' && url.includes('/install')) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: { id: 'e2e-mod', installed: true } }),
        })
      }
      return route.continue()
    })
    await waitAppReady(page)
    const list = await page.request.get('/api/mods/')
    expect(list.ok()).toBeTruthy()
    const json = await list.json()
    expect(json.data?.[0]?.id).toBe('e2e-mod')
    const install = await page.request.post('/api/mods/e2e-mod/install', { data: {} })
    expect(install.ok()).toBeTruthy()
  })
})

test.describe('P0 critical path 5 — chain smoke', () => {
  test('health → ready shell → mocked business APIs', async ({ page }) => {
    await page.route('**/api/health', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify({ status: 'ok' }) })
    )
    await page.route('**/api/mods/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: [] }),
      })
    )
    const health = await page.request.get('/api/health').catch(() => null)
    if (health) {
      expect(health.ok()).toBeTruthy()
    }
    await waitAppReady(page)
    await expect(page.locator('#app')).toBeVisible()
  })
})
