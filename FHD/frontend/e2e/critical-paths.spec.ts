import { test, expect } from '@playwright/test'
import { installE2eShellMocks, captureEvidence, csrfHeaders, isFullStack, loginBrowserSession } from './helpers'
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

  test('02 order — anonymous and tenant sessions cannot read the legacy shared store', async ({ page, request }) => {
    if (isFullStack()) {
      const anonymous = await request.get('/api/orders', { timeout: 20_000 })
      expect(anonymous.status(), await anonymous.text()).toBe(401)
      expect(await anonymous.json()).toMatchObject({ success: false, error_code: 'http_401', message: expect.stringContaining('请先登录'), path: '/api/orders' })
      const tenant = await page.request.get('/api/orders', { timeout: 20_000 })
      expect(tenant.status(), await tenant.text()).toBe(403)
      expect(await tenant.json()).toMatchObject({ success: false, error_code: 'http_403', message: '该旧业务接口尚未提供安全的租户数据隔离', path: '/api/orders' })
      await page.goto('/orders', { waitUntil: 'domcontentloaded', timeout: 30_000 })
      await expect(page).toHaveURL((url) => url.pathname === '/mod/xcagi-erp-domain-bridge/orders')
    } else {
      await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    }
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await captureEvidence(page, '02-order.png')
  })

  test('03 shipment — tenant record list has the business response contract', async ({ page }) => {
    if (isFullStack()) {
      const response = await page.request.get('/api/shipment/shipment-records/records', { timeout: 20_000 })
      expect(response.status(), await response.text()).toBe(200)
      expect(await response.json()).toMatchObject({
        success: true, data: expect.any(Array),
        source: 'mod:xcagi-erp-domain-bridge', execution_path: 'mod_domain_handler',
      })
    }
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await captureEvidence(page, '03-shipment.png')
  })

  test('04 OCR — diagnostics return the declared service schema', async ({ page }) => {
    if (isFullStack()) {
      const response = await page.request.get('/api/ocr/test', { timeout: 20_000 })
      expect(response.status(), await response.text()).toBe(200)
      const body = await response.json()
      expect(body).toMatchObject({ success: true, message: 'OCR服务运行正常' })
      expect(['paddleocr', 'easyocr', 'macos_vision', 'tesseract', 'none', 'unknown']).toContain(body.active_backend)
    }
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await captureEvidence(page, '04-ocr.png')
  })

  test('05 mod — authenticated catalog returns installed business mods', async ({ page }) => {
    if (isFullStack()) {
      const response = await page.request.get('/api/mods/', { timeout: 20_000 })
      expect(response.status(), await response.text()).toBe(200)
      const body = await response.json()
      expect(body).toMatchObject({ success: true, data: expect.any(Array) })
      expect(body.data).toEqual(expect.arrayContaining([expect.objectContaining({ id: 'xcagi-erp-domain-bridge' })]))
    }
    await page.goto('/ai-ecosystem', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    await captureEvidence(page, '05-mod.png')
  })

  test('06 tenant customer loop — 旧订单接口拒绝越权，数据对接只保留导入', async ({ page }) => {
    if (isFullStack()) {
      test.setTimeout(60_000)
      const denied = await page.request.post('/api/orders', {
        headers: await csrfHeaders(page.request),
        data: { purchase_unit: '越权订单' },
      })
      expect(denied.status(), await denied.text()).toBe(403)

      await page.goto('/business-docking', { waitUntil: 'domcontentloaded', timeout: 30_000 })
      await expect(page.locator('#view-business-docking')).toBeVisible({ timeout: 25_000 })
      await expect(page.locator('#view-business-docking')).toContainText('上传 → 自动分类 → 选模板并入库')
      await expect(page.getByRole('button', { name: '历史导入任务' })).toHaveCount(0)
      await captureEvidence(page, '06-customer-data-loop.png')
      await page.goto('/orders', { waitUntil: 'domcontentloaded', timeout: 30_000 })
      await expect(page).toHaveURL((url) => url.pathname === '/mod/xcagi-erp-domain-bridge/orders', { timeout: 25_000 })
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

  test('07 tenant product loop — 旧材料接口拒绝越权，数据对接不暴露旧导入任务', async ({ page }) => {
    test.skip(!isFullStack(), 'covered by the mandatory release full-stack job')
    test.setTimeout(60_000)
    const denied = await page.request.post('/api/materials', {
      headers: await csrfHeaders(page.request),
      data: { material_code: '越权材料', name: '越权材料' },
    })
    expect(denied.status(), await denied.text()).toBe(403)

    await page.goto('/business-docking', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('#view-business-docking')).toBeVisible({ timeout: 25_000 })
    await expect(page.getByRole('button', { name: '历史导入任务' })).toHaveCount(0)
    await captureEvidence(page, '07-product-data-loop.png')
    await page.goto('/materials', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page).toHaveURL((url) => url.pathname === '/mod/xcagi-erp-domain-bridge/materials', { timeout: 25_000 })
  })
})
