#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(path.join(root, 'frontend/package.json'))
const { chromium, expect } = require('@playwright/test')
const dir = path.resolve(process.env.XCAGI_GUI_EVIDENCE || 'candidate/evidence-Gui')
fs.mkdirSync(dir, { recursive: true })
const run = `${process.env.GITHUB_RUN_ID || Date.now()}-${process.env.GITHUB_RUN_ATTEMPT || 1}`
const phase = process.env.XCAGI_GUI_PHASE || 'business'
const seed = process.env.XCAGI_GUI_SEED ? JSON.parse(fs.readFileSync(process.env.XCAGI_GUI_SEED, 'utf8')) : null
const marker = `WIN-GUI-${run}-${phase}`
const names = { customer: `${marker}-客户`, product: `${marker}-产品`, supplier: `${marker}-供应商`, ai: `${marker}-AI客户`, cancelled: `${marker}-取消客户` }
const required = ['normal_login', 'tenant_identity', 'customer', 'product', 'purchase', 'purchase_inbound', 'sales_order', 'shipping_delivery_export', 'stock_out', 'ui_readback', 'ai_business']
if (phase === 'seed') required.splice(4)
if (seed) required.splice(2, 0, 'old_ui_readback')
if (phase === 'readback') required.splice(3)
if (phase === 'faults') required.push('controlled_stock_failure', 'authorization_cancel')
const observedRows = new Map()
const evidence = { run, phase, started_at: new Date().toISOString(), marker, names, cases: [], observations: [], result: 'running' }
let browser, page
const digest = value => crypto.createHash('sha256').update(Buffer.isBuffer(value) ? value : String(value)).digest('hex')
async function step(id, action) {
  const record = { id, started_at: new Date().toISOString(), input: names, status: 'running' }
  evidence.cases.push(record)
  try {
    record.actual = await action()
    record.status = 'passed'
    await page.screenshot({ path: path.join(dir, `${id}.png`), fullPage: true })
    return record.actual
  } catch (error) {
    record.status = 'failed'
    record.error = String(error.stack || error.message).replaceAll(process.env.XCAGI_TEST_PASS || '\0', '[REDACTED]')
    if (page) {
      await page.screenshot({ path: path.join(dir, `${id}-failed.png`), fullPage: true }).catch(() => {})
      const text = await page.locator('body').innerText().catch(() => '')
      fs.writeFileSync(path.join(dir, `${id}-ui.txt`), text.replaceAll(process.env.XCAGI_TEST_PASS || '\0', '[REDACTED]'))
    }
    throw error
  } finally { record.finished_at = new Date().toISOString() }
}
async function click(name, scope = page) { await scope.getByRole('button', { name, exact: typeof name === 'string' }).first().click() }
async function nav(key, rootId) {
  const entry = page.locator(`[data-tour="sidebar-${key}"]:visible,[data-tour="sidebar-mod-erp-${key}"]:visible`).first()
  if (!await entry.isVisible()) {
    for (const parent of await page.locator('.sidebar .menu-item.has-children:not(.expanded)').all()) await parent.click()
  }
  await entry.click()
  await expect(page.locator(rootId)).toBeVisible({ timeout: 30000 })
}
function modal() { return page.locator('.modal-content:visible').last() }
function field(label, scope = modal()) {
  return scope.locator('.form-group, .form-col, .product-cell').filter({ has: page.locator('label').filter({ hasText: label }) }).first()
}
async function fill(label, value, scope) { await field(label, scope).locator('input:not([type=hidden]),textarea').first().fill(String(value)) }
async function choose(label, text, scope) {
  const select = field(label, scope).locator('select').first()
  const option = select.locator('option').filter({ hasText: text }).first()
  await expect(option).toHaveCount(1)
  await select.selectOption(await option.getAttribute('value'))
}
async function dismissSuccessAlert() {
  const dialog = page.locator('.app-dialog-host-panel')
  await dialog.waitFor({ state: 'visible', timeout: 2000 }).catch(() => {})
  if (!await dialog.isVisible()) return
  await expect(dialog.locator('.app-dialog-host-message')).toContainText(/成功/)
  await dialog.locator('.app-dialog-host-btn-primary').click()
}
async function save(name, endpoint) {
  const waiting = page.waitForResponse(r => r.request().method() === 'POST' && endpoint.test(new URL(r.url()).pathname), { timeout: 30000 })
  const button = modal().getByRole('button', { name, exact: typeof name === 'string' }).first(), actualText = await button.innerText(); await button.evaluate(el => el.addEventListener('click', () => console.info('WIN_UI_CLICK:' + el.textContent), { once: true })); await button.click(); evidence.observations.push({ action: 'save_button_clicked', name: String(name), actualText, observed_at: new Date().toISOString() })
  const response = await waiting
  const body = await response.json()
  if (!response.ok() || body.success === false || body.ok === false) throw new Error(`Business save rejected: HTTP ${response.status()}`)
  const data = body.data || body
  const object = { endpoint: new URL(response.url()).pathname, status: response.status(), id: data.id || data.customer_id || data.product_id || data.order_id || data.inbound_id || data.ledger_id || data.order_no || data.order_number, fields: data }
  if (!object.id && phase !== 'seed') throw new Error(`Saved business response has no record identity: ${object.endpoint}`)
  await dismissSuccessAlert()
  await expect(modal()).toHaveCount(0)
  return object
}
async function openAiApproval(name) {
  await nav('chat', '#view-chat')
  const previousCardText = await page.getByTestId('chat-approval-inline-card').last().innerText().catch(() => '')
  await page.locator('#view-chat textarea').fill(`请创建客户，客户名称“${name}”，联系人“AI验收员”，电话13800000002。请执行到客户记录保存成功并给出记录编号。`)
  await click(/^发送$/)
  const card = page.getByTestId('chat-approval-inline-card').last()
  await expect.poll(() => card.innerText().then(text => Boolean(text && text !== previousCardText)).catch(() => false), { timeout: 60000 }).toBe(true)
  const submit = card.getByRole('button', { name: /^提交审批$|^确认执行$/ })
  if (await submit.isVisible()) await submit.click()
  const requestNos = (await card.locator('.approval-request-nos').innerText()).replace(/^审批请求号：/, '').split('、').map(s => s.trim()).filter(Boolean)
  if (requestNos.length !== 1) throw new Error('AI task must expose one correlated durable approval request')
  await card.getByRole('link', { name: '前往审批' }).click()
  const detail = page.locator('[data-tutorial-id="approval-detail"]')
  await expect(detail).toBeVisible({ timeout: 30000 })
  await expect(detail).toContainText(requestNos[0]); await expect(detail).toContainText(name)
  return { requestNo: requestNos[0], detail }
}
async function main() {
  if (phase === 'readback' && !seed) throw new Error('GUI recovery readback requires original business evidence')
  browser = await chromium.connectOverCDP(process.env.XCAGI_CDP || 'http://127.0.0.1:9222', { timeout: 60000 })
  const context = browser.contexts()[0]
  page = context.pages().find(p => p.url().includes('127.0.0.1:17500')) || context.pages()[0]
  page.on('response', async r => {
    if (r.request().method() !== 'GET' || !/\/(customers|products)\/list$/.test(new URL(r.url()).pathname) || !r.ok()) return
    const body = await r.json().catch(() => ({})), rows = body.data || body.customers || body.products || []
    if (Array.isArray(rows)) for (const row of rows) observedRows.set(row.customer_name || row.name || row.product_name, row)
  })
  page.on('request', r => { const endpoint = new URL(r.url()).pathname; if (r.method() === 'POST' && /purchase|inventory|customers|products|orders|shipment/.test(endpoint)) evidence.observations.push({ endpoint, method: r.method(), event: 'request_started', observed_at: new Date().toISOString() }) })
  page.on('response', r => { const endpoint = new URL(r.url()).pathname; if (r.request().method() === 'POST' && /purchase|inventory|customers|products|orders|shipment/.test(endpoint)) evidence.observations.push({ endpoint, method: r.request().method(), status: r.status(), observed_at: new Date().toISOString() }) })
  page.on('console', msg => { const text = msg.text().split('\n')[0]; if (/WIN_UI_CLICK:|TypeError|ReferenceError|Unhandled error/.test(text) && !/token|password|secret|authorization|cookie/i.test(text)) evidence.observations.push({ browser_console: text.slice(0, 512), observed_at: new Date().toISOString() }) })
  page.on('pageerror', error => evidence.observations.push({ browser_error: String(error.message).replaceAll(process.env.XCAGI_TEST_PASS || '\0', '[REDACTED]'), observed_at: new Date().toISOString() })); page.setDefaultTimeout(20000)
  await page.waitForURL(/127\.0\.0\.1:17500/, { timeout: 240000 })
  const login = await step('normal_login', async () => {
    if (!await page.locator('#lv-username').isVisible()) await click(/^登录$|企业登录/)
    await page.locator('#lv-username').fill(process.env.XCAGI_TEST_USER || '')
    await page.locator('#lv-password').fill(process.env.XCAGI_TEST_PASS || '')
    const waiting = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/auth/login')
    await page.locator('.login-form button[type=submit]').click()
    const response = await waiting
    const body = await response.json()
    const data = body.data || body
    if (body.success === false || data.success === false || !response.ok()) throw new Error('Normal UI login rejected')
    await expect(page.locator('#lv-password')).toHaveCount(0, { timeout: 30000 })
    return { status: response.status(), account_kind: data.account_kind || data.user?.account_kind, tenant_id: data.tenant_id || data.tenant?.id, workspace_id: data.workspace_id || data.user?.workspace_id || null, account_sha256: digest(process.env.XCAGI_TEST_USER || '') }
  })
  await step('tenant_identity', async () => {
    if (login.account_kind !== 'enterprise' || !login.tenant_id) throw new Error('UI login did not bind an enterprise tenant')
    return login
  })
  if (seed) await step('old_ui_readback', async () => {
    const originalLogin = seed.cases.find(c => c.id === 'normal_login').actual
    if (login.account_sha256 !== originalLogin.account_sha256 || login.tenant_id !== originalLogin.tenant_id || login.workspace_id !== originalLogin.workspace_id) throw new Error('Upgrade changed the original account, enterprise or workspace')
    const records = {}
    for (const [kind, name] of [['customer', seed.names.customer], ['product', seed.names.product]]) {
      const view = kind === 'customer' ? 'customers' : 'products'
      await nav(view, `#view-${view}`)
      const row = page.locator(`#view-${view} tbody tr`).filter({ hasText: name })
      for (const value of kind === 'customer' ? Object.values(seed.cases.find(c => c.id === kind).actual.original_fields).filter(Boolean) : [seed.marker, '¥12.50']) await expect(row).toContainText(value)
      if (kind === 'product') await expect(row.locator('td').nth(3)).toHaveText('10')
      await expect.poll(() => observedRows.get(name)?.id).toBe(seed.cases.find(c => c.id === kind).actual.id)
      if (kind === 'customer') for (const [key, value] of Object.entries(seed.cases.find(c => c.id === kind).actual.original_fields)) await expect.poll(() => observedRows.get(name)?.[key] ?? '').toBe(value)
      records[kind] = observedRows.get(name)
    }
    return { original_run: seed.run, tenant_id: login.tenant_id, workspace_id: login.workspace_id, records }
  })
  if (phase === 'readback') { evidence.result = 'gui_readback_passed'; return }
  await step('customer', async () => {
    await nav('customers', '#view-customers')
    await click('+ 新建客户')
    await fill('客户名称', names.customer); await fill('联系人', '验收员'); await fill('电话', '13800000001'); await fill('地址', `${marker}隔离验收地址`)
    const saved = await save('创建', /customers|purchase.units/)
    const row = page.locator('#view-customers tbody tr').filter({ hasText: names.customer })
    for (const value of ['验收员', '13800000001', ...(phase === 'seed' ? [] : [`${marker}隔离验收地址`])]) await expect(row).toContainText(value)
    await expect.poll(() => observedRows.get(names.customer)?.id).toBe(saved.id)
    return { ...saved, original_fields: Object.fromEntries(['contact_person', 'contact_phone', 'contact_address'].map(key => [key, observedRows.get(names.customer)?.[key] ?? ''])), input_address: `${marker}隔离验收地址` }
  })
  await step('product', async () => {
    await nav('products', '#view-products')
    await click('+ 添加产品')
    await fill('产品型号', marker); await fill('产品名称', names.product); await fill('规格', '10'); await fill('价格', '12.50')
    const saved = await save('保存', /products/)
    const cells = page.locator('#view-products tbody tr').filter({ hasText: names.product }).locator('td')
    await expect(cells.nth(1)).toHaveText(marker)
    await expect(cells.nth(3)).toHaveText('10')
    await expect(cells.nth(4)).toHaveText('¥12.50')
    await expect.poll(() => observedRows.get(names.product)?.id).toBeTruthy()
    return { ...saved, id: observedRows.get(names.product).id, original_fields: observedRows.get(names.product) }
  })
  if (phase === 'seed') {
    await nav('settings', '#view-settings'); await click('退出登录')
    const confirmation = page.locator('.app-dialog-host-panel')
    await expect(confirmation).toContainText(/退出登录|退出本机账号/)
    const signedOut = page.waitForResponse(r => new URL(r.url()).pathname === '/api/auth/logout')
    await confirmation.locator('.app-dialog-host-btn-primary').click()
    if (!(await signedOut).ok()) throw new Error('Normal sign-out failed before upgrade')
    await expect(page.locator('#lv-username')).toBeVisible()
    evidence.result = 'old_ui_seed_passed'; return
  }
  await step('purchase', async () => {
    await nav('purchase', '#view-purchase')
    await click('供应商'); await click('添加供应商')
    await fill('编码', marker); await fill('名称', names.supplier); await fill('联系人', '采购验收员')
    await save('保存', /suppliers/)
    await click('采购订单'); await click('新建采购订单')
    await choose('供应商', names.supplier)
    await click('+ 添加产品', modal())
    const row = modal().locator('tbody tr').first()
    const product = row.locator('select')
    await product.selectOption(await product.locator('option').filter({ hasText: names.product }).getAttribute('value'))
    await row.locator('input[type=number]').nth(0).fill('10'); await row.locator('input[type=number]').nth(1).fill('12.50')
    await fill('备注', marker)
    const purchase = await save('保存', /purchase\/orders/)
    const order = page.locator('tr').filter({ hasText: names.supplier }).first()
    await click('审核', order)
    const confirm = page.getByRole('button', { name: /^确定$|^确认$/ }).first()
    await expect(confirm).toBeVisible()
    const approval = page.waitForResponse(r => r.request().method() === 'POST' && /purchase\/orders\/\d+\/approve/.test(new URL(r.url()).pathname))
    await confirm.click()
    const approved = await approval
    if (!approved.ok() || (await approved.json()).success === false) throw new Error('Purchase approval rejected')
    await dismissSuccessAlert()
    await expect(order).toContainText('已审核')
    return purchase
  })
  await step('purchase_inbound', async () => {
    const row = page.locator('tr').filter({ hasText: names.supplier }).first()
    await click(/^入库$|确认收货/, row)
    await click('新建收货仓库', modal())
    const prompt = page.locator('.app-dialog-host-panel')
    await prompt.locator('input').fill(`${marker}-收货仓库`)
    const warehouse = page.waitForResponse(r => r.request().method() === 'POST' && /inventory\/warehouses/.test(new URL(r.url()).pathname))
    await prompt.locator('.app-dialog-host-btn-primary').click()
    const warehouseResponse = await warehouse
    if (!warehouseResponse.ok() || !(await warehouseResponse.json()).data?.id) throw new Error('Normal UI warehouse creation failed')
    await expect(field('收货仓库').locator('select')).toHaveValue(String((await warehouseResponse.json()).data.id)); await modal().getByLabel('数量').fill('10')
    const saved = await save('确认入库', /purchase\/inbounds/)
    await click('采购入库')
    const receipt = page.locator('#view-purchase tbody tr').filter({ hasText: names.supplier })
    await expect(receipt).toContainText('¥125.00')
    await expect(receipt).toContainText('completed')
    await click('采购订单')
    await expect(page.locator('#view-purchase tbody tr').filter({ hasText: names.supplier })).toContainText('已完成')
    await nav('inventory', '#view-inventory')
    const stock = page.locator('#view-inventory tbody tr').filter({ hasText: names.product }).locator('td')
    await expect(stock.nth(4)).toHaveText('10')
    await expect(stock.nth(5)).toHaveText('10')
    return saved
  })
  await step('sales_order', async () => {
    await nav('orders', '#view-orders'); await click('+ 新建订单')
    const form = page.locator('#view-create-order')
    await expect(form).toBeVisible()
    await choose('购买单位', names.customer, form)
    await click(/添加产品/, form)
    await choose('产品名称', names.product, form)
    await fill('数量/件', '2', form); await fill('规格/KG', '10', form); await fill('单价/元', '12.50', form)
    const options = field('发货单模板', form).locator('select option[value]:not([value=""])')
    if (!await options.count()) throw new Error('Promised delivery template unavailable in the installed app')
    await field('发货单模板', form).locator('select').selectOption(await options.first().getAttribute('value'))
    const pending = page.waitForResponse(r => r.request().method() === 'POST' && /orders|shipment.*generate/.test(new URL(r.url()).pathname))
    await click('生成发货单', form)
    const response = await pending
    const body = await response.json(); const data = body.data || body
    if (!response.ok() || body.success === false || !(data.order_id || data.order_number)) throw new Error('Sales order identity not produced by normal UI')
    return { order_id: data.order_id, order_number: data.order_number, output_file: data.output_file || data.file_path }
  })
  await step('shipping_delivery_export', async () => {
    const waiting = page.waitForEvent('download', { timeout: 30000 })
    await click(/下载.*送货单|下载.*发货单|导出.*送货单|下载文件/)
    const download = await waiting
    const filename = path.basename(download.suggestedFilename()), target = path.join(dir, filename)
    await download.saveAs(target); if ((await download.failure()) || fs.statSync(target).size === 0) throw new Error('Delivery document export did not produce a file')
    if (!/\.xlsx?$/i.test(filename)) throw new Error('Delivery output requires a format-specific content verifier before acceptance')
    const XLSX = require('xlsx'); const workbook = XLSX.readFile(target)
    const contents = workbook.SheetNames.map(name => XLSX.utils.sheet_to_csv(workbook.Sheets[name])).join('\n')
    if (!contents.includes(names.customer) || !contents.includes(names.product)) throw new Error('Exported delivery note does not contain the expected customer and product')
    const rows = workbook.SheetNames.flatMap(name => XLSX.utils.sheet_to_json(workbook.Sheets[name], { header: 1 }))
    const productRow = rows.find(row => row.some(cell => String(cell).includes(names.product)))
    const values = (productRow || []).map(cell => Number(String(cell).replace(/[￥¥,元]/g, '')))
    if (![2, 20, 12.5, 250].every(value => values.includes(value))) throw new Error('Delivery row quantity, unit price or amount differs from the submitted business input')
    return { filename, bytes: fs.statSync(target).size, sha256: digest(fs.readFileSync(target)) }
  })
  await step('stock_out', async () => {
    await nav('inventory', '#view-inventory'); await click('出库')
    await choose('产品', names.product); await choose('仓库', `${marker}-收货仓库`)
    await fill('数量', '2')
    const order = evidence.cases.find(c => c.id === 'sales_order').actual
    await fill('备注', `${marker} 送货单 ${order.order_number}`)
    const saved = await save('确认出库', /inventory\/out$/)
    if (saved.fields.quantity !== 2 || saved.fields.remaining_quantity !== 8) throw new Error('Actual stock movement differs from the submitted shipment quantity')
    const cells = page.locator('#view-inventory tbody tr').filter({ hasText: names.product }).locator('td')
    await expect(cells.nth(4)).toHaveText('8'); await expect(cells.nth(5)).toHaveText('8')
    return { ...saved, order_number: order.order_number, expected_remaining_quantity: 8 }
  })
  await step('ui_readback', async () => {
    await nav('orders', '#view-orders'); await expect(page.locator('#view-orders')).toContainText(names.customer)
    await nav('customers', '#view-customers'); await expect(page.locator('#view-customers')).toContainText(names.customer)
    await nav('products', '#view-products'); await expect(page.locator('#view-products')).toContainText(names.product)
    return { customer: names.customer, product: names.product }
  })
  await step('ai_business', async () => {
    const { requestNo } = await openAiApproval(names.ai)
    const approve = page.locator('[data-tutorial-id="approval-approve-action"]')
    await approve.click()
    const dialog = page.locator('.app-dialog-host-panel')
    await expect(dialog).toContainText('请输入审批意见')
    await dialog.locator('input').fill(`${marker} 正常审批同意`)
    const execution = page.waitForResponse(r => r.request().method() === 'POST' && /approval.*approve/.test(new URL(r.url()).pathname), { timeout: 180000 })
    await dialog.locator('.app-dialog-host-btn-primary').click()
    const response = await execution, body = await response.json(), result = body.data?.workflow_execution
    if (!response.ok() || body.success !== true || result?.workflow_executed !== true || result.success !== true) throw new Error('Approval did not complete the real AI workflow')
    await expect(dialog).toContainText('执行完成', { timeout: 180000 })
    const receiptText = await dialog.innerText(); evidence.observations.push({ action: 'ai_execution_receipt', approval_request: requestNo, execution: result, receipt: receiptText, observed_at: new Date().toISOString() })
    await dialog.locator('.app-dialog-host-btn-primary').click()
    if (await modal().isVisible()) await modal().getByRole('button', { name: /关闭/ }).first().click()
    await page.reload(); evidence.observations.push({ action: 'normal_ui_reload_before_ai_readback', observed_at: new Date().toISOString() }); await nav('customers', '#view-customers')
    const row = page.locator('#view-customers tbody tr').filter({ hasText: names.ai })
    for (const value of [names.ai, 'AI验收员', '13800000002']) await expect(row).toContainText(value, { timeout: 30000 })
    await expect.poll(() => observedRows.get(names.ai)?.id).toBeTruthy()
    return { created_customer: names.ai, id: observedRows.get(names.ai).id, fields: observedRows.get(names.ai), approval_request: requestNo, execution: result, receipt: receiptText }
  })
  if (phase === 'faults') {
    await step('controlled_stock_failure', async () => {
      await nav('inventory', '#view-inventory'); await click('出库')
      await choose('产品', names.product); await choose('仓库', `${marker}-收货仓库`); await fill('数量', '999')
      const rejected = page.waitForResponse(r => r.request().method() === 'POST' && /inventory\/out$/.test(new URL(r.url()).pathname))
      await modal().getByRole('button', { name: '确认出库', exact: true }).click()
      const response = await rejected, body = await response.json(); evidence.observations.push({ action: 'controlled_stock_failure_response', http_status: response.status(), result: body, observed_at: new Date().toISOString() })
      if (body.success !== false || !/库存不足/.test(JSON.stringify(body))) throw new Error('Overdraw did not reject with a real insufficient-stock result')
      const dialog = page.locator('.app-dialog-host-panel'); await expect(dialog).toContainText('出库失败')
      await dialog.locator('.app-dialog-host-btn-primary').click(); await modal().getByRole('button', { name: '取消', exact: true }).click()
      await nav('products', '#view-products'); await nav('inventory', '#view-inventory')
      const cells = page.locator('#view-inventory tbody tr').filter({ hasText: names.product }).locator('td')
      await expect(cells.nth(4)).toHaveText('8'); await expect(cells.nth(5)).toHaveText('8')
      return { requested_quantity: 999, rejected: body, actual_remaining_quantity: 8, http_status: response.status() }
    })
    await step('authorization_cancel', async () => {
      const { requestNo, detail } = await openAiApproval(names.cancelled), dialog = page.locator('.app-dialog-host-panel')
      await detail.getByRole('button', { name: '通过', exact: true }).click(); await expect(dialog).toContainText('请输入审批意见')
      await dialog.locator('.app-dialog-host-btn-secondary').click(); await expect(dialog).not.toBeVisible()
      await detail.getByRole('button', { name: '拒绝', exact: true }).click(); await dialog.locator('input').fill(`${marker} 取消本次业务授权`)
      const rejected = page.waitForResponse(r => r.request().method() === 'POST' && /approval.*reject/.test(new URL(r.url()).pathname))
      await dialog.locator('.app-dialog-host-btn-primary').click()
      const response = await rejected, body = await response.json()
      if (!response.ok() || body.success !== true || body.data?.status !== 'rejected' || body.data?.workflow_execution?.workflow_executed !== false) throw new Error('Cancelled authorization did not terminate without execution')
      await expect(dialog).toContainText('已拒绝'); await dialog.locator('.app-dialog-host-btn-primary').click()
      await page.reload(); await nav('customers', '#view-customers'); await expect(page.locator('#view-customers')).toContainText(names.ai)
      await expect(page.locator('#view-customers')).not.toContainText(names.cancelled)
      return { approval_request: requestNo, cancelled_customer: names.cancelled, rejection: body.data, gui_customer_absent: true }
    })
  }
  evidence.result = 'business_regression_passed'
}
try { await main() } catch (error) { evidence.result = 'failed'; evidence.failure = String(error.message).replaceAll(process.env.XCAGI_TEST_PASS || '\0', '[REDACTED]'); process.exitCode = 1 }
finally {
  evidence.finished_at = new Date().toISOString()
  evidence.unfinished = required.filter(id => !evidence.cases.some(c => c.id === id && c.status === 'passed'))
  evidence.full_customer_acceptance = 'not_verified' // Independent A/B/C, binding, restart and recovery are separate obligations.
  fs.writeFileSync(path.join(dir, 'gui-business.json'), JSON.stringify(evidence, null, 2))
  if (browser) await browser.close().catch(() => {})
}
