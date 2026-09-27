import { test, expect } from '@playwright/test'
import { installE2eShellMocks, captureEvidence, csrfHeaders, isFullStack, loginBrowserSession } from './helpers'
import { exportEtlRowsCsv, importBusinessCsv } from './etl-business'

test.describe('P0 critical paths', () => {
  test.beforeEach(async ({ page }) => {
    if (!isFullStack()) {
      await installE2eShellMocks(page)
    } else {
      await loginBrowserSession(page)
    }
  })

  test('01 login — credentials establish session', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('#app')).toBeVisible()
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await captureEvidence(page, '01-login.png')
  })

  test('02 order — orders list API reachable', async ({ page, request }) => {
    if (isFullStack()) {
      const resp = await request.get('/api/orders', { timeout: 20_000 })
      expect(resp.status(), await resp.text()).toBeLessThan(500)
    }

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    const orderNav = page.getByRole('button', { name: /订单|发货单|创建订单/ }).first()
    if (await orderNav.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await orderNav.click()
    }
    await captureEvidence(page, '02-order.png')
  })

  test('03 shipment — shipment list API reachable', async ({ page, request }) => {
    if (isFullStack()) {
      const resp = await request.get('/api/shipment/list', { timeout: 20_000 })
      expect(resp.status(), await resp.text()).toBeLessThan(500)
    }

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await captureEvidence(page, '03-shipment.png')
  })

  test('04 OCR — ocr test endpoint reachable', async ({ page, request }) => {
    if (isFullStack()) {
      const resp = await request.get('/api/ocr/test', { timeout: 20_000 })
      expect(resp.status(), await resp.text()).toBeLessThan(500)
    }

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await captureEvidence(page, '04-ocr.png')
  })

  test('05 mod — mods list API reachable', async ({ page, request }) => {
    if (isFullStack()) {
      const resp = await request.get('/api/mods/', { timeout: 20_000 })
      expect(resp.status(), await resp.text()).toBeLessThan(500)
    }

    await page.goto('/ai-ecosystem', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await captureEvidence(page, '05-mod.png')
  })

  test('06 tenant customer loop — 创建、编辑、回读并经 ETL 导出', async ({ page }) => {
    if (isFullStack()) {
      test.setTimeout(180_000)
      const denied = await page.request.post('/api/orders', {
        headers: await csrfHeaders(page.request),
        data: { purchase_unit: '越权订单' },
      })
      expect(denied.status(), await denied.text()).toBe(403)

      await page.goto('/business-docking', { waitUntil: 'domcontentloaded', timeout: 30_000 })
      await expect(page.locator('#view-business-docking')).toBeVisible({ timeout: 25_000 })
      const name = `E2E客户-${Date.now()}`
      const created = await importBusinessCsv(page, 'customers',
        `客户名称,联系人,电话,地址\n${name},验收员,13000000001,原地址\n`, 'new')
      expect(created.row.after.customer_name).toBe(name)
      const updated = await importBusinessCsv(page, 'customers',
        `客户名称,联系人,电话,地址\n${name},验收员,13000000002,新地址\n`, 'update',
        ['contact_phone', 'contact_address'])
      expect(updated.row.match_ref).toBe(created.row.match_ref)
      expect(updated.row.before.contact_phone).toBe('13000000001')
      expect(updated.row.after.contact_phone).toBe('13000000002')
      expect(updated.row.after.contact_address).toBe('新地址')
      // The exported source is the completed, owner-scoped ETL row readback.
      const exported = await exportEtlRowsCsv(page,
        `客户名称,电话\n${updated.row.after.customer_name},${updated.row.after.contact_phone}\n`)
      expect(exported.text).toContain(`${name},13000000002`)
      expect(exported.sha256).toHaveLength(64)
      await captureEvidence(page, '06-customer-data-loop.png')
      await page.goto('/orders', { waitUntil: 'domcontentloaded', timeout: 30_000 })
      await expect(page).toHaveURL((url) => url.pathname === '/settings', { timeout: 25_000 })
      return
    }
    const order = {
      id: 1001,
      purchase_unit: 'E2E客户',
      product_name: 'E2E产品',
      quantity_kg: 10,
      status: 'pending',
    }
    await page.route('**/api/orders', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, shipment: order }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: [order] }),
      })
    })
    await page.route('**/api/orders/1001', (route) => {
      if (route.request().method() === 'PATCH') {
        Object.assign(order, JSON.parse(route.request().postData() || '{}'))
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: order }),
      })
    })
    await page.route('**/api/orders/export', (route) => route.fulfill({
      status: 200,
      contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      body: 'mock-xlsx',
    }))
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    const result = await page.evaluate(async () => {
      const created = await fetch('/api/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ purchase_unit: 'E2E客户' }),
      })
      const createBody = await created.json()
      const edited = await fetch('/api/orders/1001', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ purchase_unit: 'E2E客户-已编辑', status: 'completed' }),
      })
      const read = await fetch('/api/orders/1001')
      const exported = await fetch('/api/orders/export')
      return {
        createStatus: created.status,
        createId: createBody.shipment.id,
        editStatus: edited.status,
        read: (await read.json()).data,
        exportStatus: exported.status,
        exportBody: await exported.text(),
      }
    })
    expect(result.createStatus).toBe(201)
    expect(result.createId).toBe(1001)
    expect(result.editStatus).toBe(200)
    expect(result.read).toMatchObject({ purchase_unit: 'E2E客户-已编辑', status: 'completed' })
    expect(result.exportStatus).toBe(200)
    expect(result.exportBody).toBe('mock-xlsx')
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await captureEvidence(page, '06-order-data-loop.png')
  })

  test('07 tenant product loop — 创建、编辑、回读并经 ETL 导出', async ({ page }) => {
    test.skip(!isFullStack(), 'covered by the mandatory release full-stack job')
    test.setTimeout(180_000)
    const denied = await page.request.post('/api/materials', {
      headers: await csrfHeaders(page.request),
      data: { material_code: '越权材料', name: '越权材料' },
    })
    expect(denied.status(), await denied.text()).toBe(403)

    await page.goto('/business-docking', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('#view-business-docking')).toBeVisible({ timeout: 25_000 })
    const stamp = Date.now()
    const unit = `E2E单位-${stamp}`
    const model = `E2E型号-${stamp}`
    const created = await importBusinessCsv(page, 'products',
      `购买单位,型号,产品名称,价格\n${unit},${model},E2E产品,8.50\n`, 'new')
    expect(created.row.after.model_number).toBe(model)
    const updated = await importBusinessCsv(page, 'products',
      `购买单位,型号,产品名称,价格\n${unit},${model},E2E产品,9.75\n`, 'update', ['price'])
    expect(updated.row.match_ref).toBe(created.row.match_ref)
    expect(Number(updated.row.before.price)).toBe(8.5)
    expect(Number(updated.row.after.price)).toBe(9.75)
    const exported = await exportEtlRowsCsv(page,
      `购买单位,型号,产品名称,价格\n${unit},${model},E2E产品,${updated.row.after.price}\n`)
    expect(exported.text).toContain(`${unit},${model},E2E产品,9.75`)
    expect(exported.sha256).toHaveLength(64)
    await captureEvidence(page, '07-product-data-loop.png')
    await page.goto('/materials', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page).toHaveURL((url) => url.pathname === '/settings', { timeout: 25_000 })
  })
})
