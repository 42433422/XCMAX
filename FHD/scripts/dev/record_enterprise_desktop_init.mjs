#!/usr/bin/env node
/** Installed Windows UI regression. No mocks, API writes, storage injection or synthetic video. */
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
const marker = `WIN-GUI-${run}`
const names = { customer: `${marker}-客户`, product: `${marker}-产品`, supplier: `${marker}-供应商`, ai: `${marker}-AI客户` }
const required = ['normal_login', 'tenant_identity', 'customer', 'product', 'purchase', 'purchase_inbound', 'sales_order', 'shipping_delivery_export', 'ui_readback', 'ai_business']
const evidence = { run, started_at: new Date().toISOString(), marker, names, cases: [], observations: [], result: 'running' }
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
    record.error = String(error.message).replaceAll(process.env.XCAGI_TEST_PASS || '\0', '[REDACTED]')
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
  await click(name, modal())
  const response = await waiting
  const body = await response.json()
  if (!response.ok() || body.success === false || body.ok === false) throw new Error(`Business save rejected: HTTP ${response.status()}`)
  const data = body.data || body
  const object = { endpoint: new URL(response.url()).pathname, status: response.status(), id: data.id || data.customer_id || data.product_id || data.order_id || data.inbound_id || data.order_no || data.order_number }
  if (!object.id) throw new Error(`Saved business response has no record identity: ${object.endpoint}`)
  evidence.observations.push(object)
  await dismissSuccessAlert()
  await expect(modal()).toHaveCount(0)
  return object
}
async function main() {
  browser = await chromium.connectOverCDP(process.env.XCAGI_CDP || 'http://127.0.0.1:9222', { timeout: 60000 })
  const context = browser.contexts()[0]
  page = context.pages().find(p => p.url().includes('127.0.0.1:17500')) || context.pages()[0]
  page.setDefaultTimeout(20000)
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
    return { status: response.status(), account_kind: data.account_kind || data.user?.account_kind, tenant_id: data.tenant_id || data.tenant?.id, workspace_id: data.workspace_id || data.user?.workspace_id, account_sha256: digest(process.env.XCAGI_TEST_USER || '') }
  })
  await step('tenant_identity', async () => {
    if (login.account_kind !== 'enterprise' || !login.tenant_id) throw new Error('UI login did not bind an enterprise tenant')
    return login
  })
  await step('customer', async () => {
    await nav('customers', '#view-customers')
    await click('+ 新建客户')
    await fill('客户名称', names.customer); await fill('联系人', '验收员'); await fill('电话', '13800000001'); await fill('地址', `${marker}隔离验收地址`)
    const saved = await save('创建', /customers|purchase.units/)
    await expect(page.locator('#view-customers')).toContainText(names.customer)
    return saved
  })
  await step('product', async () => {
    await nav('products', '#view-products')
    await click('+ 添加产品')
    await fill('产品型号', marker); await fill('产品名称', names.product); await fill('规格', '10'); await fill('价格', '12.50')
    const saved = await save('保存', /products/)
    await expect(page.locator('#view-products')).toContainText(names.product)
    return saved
  })
  let purchase
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
    purchase = await save('保存', /purchase\/orders/)
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
    await fill('数量', '10')
    const saved = await save(/^确认入库$|^保存$/, /purchase\/inbounds/)
    await click('采购入库')
    await expect(page.locator('#view-purchase')).toContainText(names.supplier)
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
    const filename = path.basename(download.suggestedFilename()); const target = path.join(dir, filename)
    await download.saveAs(target)
    if ((await download.failure()) || fs.statSync(target).size === 0) throw new Error('Delivery document export did not produce a file')
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
  await step('ui_readback', async () => {
    await nav('orders', '#view-orders'); await expect(page.locator('#view-orders')).toContainText(names.customer)
    await nav('customers', '#view-customers'); await expect(page.locator('#view-customers')).toContainText(names.customer)
    await nav('products', '#view-products'); await expect(page.locator('#view-products')).toContainText(names.product)
    return { customer: names.customer, product: names.product }
  })
  await step('ai_business', async () => {
    await page.locator('[data-tour="sidebar-im"]').click()
    const input = page.locator('textarea:visible').last()
    await input.fill(`请创建客户，客户名称“${names.ai}”，联系人“AI验收员”，电话13800000002。请执行到客户记录保存成功并给出记录编号。`)
    await click(/^发送$/)
    const approve = page.getByRole('button', { name: /^批准$|^同意执行$|^确认执行$/ }).first()
    await approve.waitFor({ state: 'visible', timeout: 30000 }).catch(() => {})
    if (await approve.isVisible()) await approve.click()
    await expect(page.locator('body')).toContainText(/执行成功|已完成|创建成功/, { timeout: 180000 })
    await nav('customers', '#view-customers')
    await expect(page.locator('#view-customers')).toContainText(names.ai, { timeout: 30000 })
    return { created_customer: names.ai }
  })
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
