#!/usr/bin/env node
/**
 * P-App / P-W / P-S 表面巡检：Playwright 截全量页面 PNG + console 采集。
 *
 * 用法:
 *   node scripts/ci/run_surface_audit.mjs P-App [--refresh] [--out /tmp/audit.json]
 *
 * 环境:
 *   SURFACE_AUDIT_BASE_URL   — FHD Vite 前端（默认 http://127.0.0.1:5001）
 *   SURFACE_AUDIT_MARKETING_BASE_URL — 营销静态站（默认 https://xiu-ci.com）
 *   XCAGI_MARKET_BASE_URL    — MODstore 市场（工作台 / P-S 页）
 *   SURFACE_AUDIT_SAMPLE_MOD_ID — Mod WebView 样例 id
 */
import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import {
  loginSurfaceAuditForLane,
  playwrightCookies,
  fetchDigestIdentity,
  verifyAdminDigestCode,
} from './surface_audit_auth.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FHD_ROOT = path.resolve(__dirname, '../..')
const requireFromFrontend = createRequire(path.join(FHD_ROOT, 'frontend/package.json'))
const { chromium } = requireFromFrontend('playwright')
const CONFIG_PATH = path.join(FHD_ROOT, 'config/surface_audit_pages.json')

const laneArg = (process.argv.find((a) => !a.startsWith('-') && a !== process.argv[0] && a !== process.argv[1]) || 'P-App')
const outArgIdx = process.argv.indexOf('--out')
const OUT_PATH = outArgIdx >= 0 ? process.argv[outArgIdx + 1] : ''

const FHD_BASE = (process.env.SURFACE_AUDIT_BASE_URL || 'http://127.0.0.1:5001').replace(/\/$/, '')
const ADMIN_BASE = (
  process.env.SURFACE_AUDIT_ADMIN_BASE_URL ||
  process.env.SURFACE_AUDIT_API_URL ||
  'http://127.0.0.1:5000'
).replace(/\/$/, '')
const MARKETING_BASE = (
  process.env.SURFACE_AUDIT_MARKETING_BASE_URL ||
  process.env.MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL ||
  'https://xiu-ci.com'
).replace(/\/$/, '')
const MARKET_BASE = (process.env.XCAGI_MARKET_BASE_URL || process.env.MODSTORE_BASE_URL || 'http://127.0.0.1:5176').replace(/\/$/, '')

let _auditAuth = null

async function ensureAuditAuth() {
  if (_auditAuth) return _auditAuth
  _auditAuth = await loginSurfaceAuditForLane(laneArg)
  return _auditAuth
}

function auditProductSku() {
  return process.env.SURFACE_AUDIT_PRODUCT_SKU || 'personal'
}

function auditDateKey() {
  try {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: process.env.SURFACE_AUDIT_TZ || 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date())
  } catch {
    const d = new Date()
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    return local.toISOString().slice(0, 10)
  }
}

function buildAuthInitScript() {
  const sku = auditProductSku()
  const enterpriseAuditMocks =
    sku === 'enterprise'
      ? `
    if (url.includes('/api/auth/me')) {
      return new Response(JSON.stringify({
        success: true,
        data: {
          user: { id: 3, username: 'xcagi-enterprise-demo', display_name: '企业版演示' },
          account_kind: 'enterprise',
          company_brand: '修茈演示企业',
          market_is_admin: false,
          market_is_enterprise: true,
        },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    if (/\\/api\\/mods\\/loading-status/.test(url)) {
      return new Response(JSON.stringify({
        success: true,
        data: { loaded: true, mod_count: 0, discovered_mod_ids: [], registered_mod_ids: [] },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    if (/\\/api\\/mods\\/?(?:\\?|$)/.test(url)) {
      return new Response(JSON.stringify({ success: true, data: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }`
      : ''
  return `(() => {
  const sku = ${JSON.stringify(sku)};
  const orig = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.includes('/api/runtime/product-sku')) {
      return new Response(JSON.stringify({ success: true, data: { sku } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.includes('/api/auth/subscription/status')) {
      return new Response(JSON.stringify({
        success: true,
        data: { active: true, reason: 'surface_audit_demo', plan_id: 'saas-enterprise' },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }${enterpriseAuditMocks}
    return orig(input, init);
  };
})();`
}

/** P-S / P-App Web 回退：禁用 Mod 壳，展示标准企业版客户端侧栏 */
const ENTERPRISE_CLIENT_INIT_SCRIPT = `(() => {
  try {
    localStorage.setItem('xcagi_client_mods_ui_off', '1');
    localStorage.setItem('xcagi_platform_shell_mode', '0');
    localStorage.setItem('xcagi_planner_mod_facade_enabled', '0');
    localStorage.removeItem('xcagi_active_extension_mod_id');
  } catch {
    /* ignore */
  }
})();`

function needsEnterpriseClientInit(laneKey, pageDef) {
  if (laneKey !== 'P-S' && laneKey !== 'P-App') return false
  if (pageDef.native || pageDef.admin) return false
  if (pageDef.base === 'marketing' || pageDef.base === 'market') return false
  return true
}

function nativePlaceholderHtml(pageDef, lane) {
  const title = pageDef.name || pageDef.id
  const route = pageDef.android_route || pageDef.id
  return `<!DOCTYPE html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  *{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#0f1419;color:#e6edf3;min-height:100vh;display:flex;flex-direction:column}
  header{padding:16px 20px;background:#161b22;border-bottom:1px solid #30363d}
  h1{font-size:18px;margin:0}p{margin:8px 0 0;font-size:13px;color:#8b949e}
  main{flex:1;padding:24px 20px;display:flex;align-items:center;justify-content:center}
  .card{max-width:320px;padding:20px;border:1px dashed #58e2c2;border-radius:12px;text-align:center;background:#161b22}
  .tag{display:inline-block;margin-top:12px;padding:4px 10px;border-radius:999px;background:#1f6feb33;color:#58a6ff;font-size:12px}
</style></head><body>
<header><h1>${title}</h1><p>Android 原生屏 · ${route}</p></header>
<main><div class="card"><div>📱 原生 Compose 页面</div><div class="tag">${lane} · 巡检占位</div><p style="margin-top:16px;font-size:12px;color:#8b949e">Web 无等价路由；设 SURFACE_AUDIT_ANDROID=1 走 adb 真机截图。</p></div></main>
</body></html>`
}

function resolveAdminBase() {
  if (laneArg === 'P-W') {
    return (process.env.SURFACE_AUDIT_ADMIN_BASE_URL || MARKETING_BASE).replace(/\/$/, '')
  }
  return ADMIN_BASE
}

function cookieHostForUrl(url) {
  try {
    return new URL(url).hostname || '127.0.0.1'
  } catch {
    return '127.0.0.1'
  }
}

function needsMarketAuth(pageDef, url) {
  if (pageDef.market_public) return false
  if (pageDef.base === 'market') return pathNeedsMarketAuth(pageDef.path || '')
  return pathNeedsMarketAuth(pageDef.path || url || '')
}

async function injectMarketAuth(context, auditAuth) {
  const access = String(auditAuth?.market_access_token || auditAuth?.access_token || '').trim()
  if (!access) return
  const refresh = String(auditAuth?.market_refresh_token || auditAuth?.refresh_token || '').trim()
  await context.addInitScript(
    ({ access, refresh }) => {
      try {
        localStorage.setItem('modstore_token', access)
        if (refresh) localStorage.setItem('modstore_refresh_token', refresh)
      } catch {
        /* ignore */
      }
    },
    { access, refresh },
  )
}

function isMarketAdminPage(pageDef) {
  return !!(
    pageDef?.admin &&
    pageDef?.base === 'market' &&
    String(pageDef?.path || '').includes('/admin/')
  )
}

function resolveUrl(pageDef, laneCfg) {
  if (pageDef.native) return null
  if (pageDef.base === 'admin') {
    let p = pageDef.path || '/xcmax-admin'
    if (pageDef.path_template) {
      const modId = process.env[pageDef.mod_id_env || 'SURFACE_AUDIT_SAMPLE_MOD_ID'] || pageDef.mod_id_default || 'taiyangniao-pro'
      p = pageDef.path_template.replace('{mod_id}', modId)
    }
    if (!p.startsWith('/')) p = `/${p}`
    return `${resolveAdminBase()}/admin/#${p}`
  }
  let base = FHD_BASE
  if (pageDef.base === 'marketing') base = MARKETING_BASE
  if (pageDef.base === 'market') base = MARKET_BASE
  let p = pageDef.path || ''
  if (pageDef.path_template) {
    const modId = process.env[pageDef.mod_id_env || 'SURFACE_AUDIT_SAMPLE_MOD_ID'] || pageDef.mod_id_default || 'taiyangniao-pro'
    p = pageDef.path_template.replace('{mod_id}', modId)
  }
  if (!p.startsWith('/')) p = `/${p}`
  let url = `${base}${p}`
  if (base === FHD_BASE && !pageDef.admin && !pageDef.native) {
    try {
      const u = new URL(url)
      u.searchParams.set('nosplash', '1')
      if (auditProductSku() === 'enterprise') u.searchParams.set('full', '1')
      url = u.toString()
    } catch {
      /* keep raw url */
    }
  }
  return url
}

function analyzePage(pageResult) {
  const lines = []
  const status = pageResult.status || 0
  if (pageResult.error) {
    const head = String(pageResult.error).split('\n')[0].slice(0, 160)
    lines.push(
      pageResult.screenshot_saved
        ? `导航异常（已兜底截当前屏）: ${head}`
        : `导航/截图失败: ${head}`,
    )
  }
  if (status >= 400) lines.push(`HTTP ${status}：页面未正常打开`)
  const ce = (pageResult.console_errors || []).filter((m) => !pageResult.error || m !== String(pageResult.error))
  if (ce.length) lines.push(`控制台错误 ${ce.length} 条，需排查 JS 异常`)
  if (pageResult.native) lines.push('原生屏占位截图（Web 无等价 URL）')
  if (!lines.length) lines.push('表面巡检通过：无 console error、HTTP 正常')
  return lines
}

/** 远程站点（xiu-ci.com 等）易抖动：goto 失败后降级 waitUntil 再试一次 */
async function gotoWithRetry(page, url, timeoutMs) {
  try {
    return await page.goto(url, { waitUntil: 'domcontentloaded', timeout: timeoutMs })
  } catch (err) {
    const resp = await page
      .goto(url, { waitUntil: 'commit', timeout: timeoutMs })
      .catch(() => null)
    if (!resp) throw err
    await page.waitForLoadState('domcontentloaded', { timeout: timeoutMs }).catch(() => {})
    return resp
  }
}

const CJK_FONT_CSS = [
  'https://fonts.googleapis.cn/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap',
  'https://fonts.loli.net/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap',
  'https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap',
]

const AI_STORE_TAB_LABELS = {
  all: '全部商品',
  host_foundation: '宿主基础员工',
  office: '办公员工包',
  workflow: '工作流员工',
  ai_employee: 'AI 员工',
}

const MARKET_AUTH_SKIP_PREFIXES = [
  '/market/login',
  '/market/register',
  '/market/login-email',
  '/market/forgot-password',
]

function pathNeedsMarketAuth(path) {
  const p = String(path || '').trim()
  if (!p.includes('/market')) return false
  for (const skip of MARKET_AUTH_SKIP_PREFIXES) {
    if (p === skip || p.startsWith(`${skip}/`) || p.startsWith(`${skip}?`)) return false
  }
  return true
}

const WB_MODE_LABELS = {
  direct: '聊',
  make: '做',
  voice: '说',
}

async function applySinglePrepare(page, prepare) {
  if (!prepare) return
  if (prepare.startsWith('wb_mode:')) {
    const mode = prepare.split(':')[1]
    const label = WB_MODE_LABELS[mode]
    if (!label) return
    try {
      await page.locator('.wb-sidebar-modes button.wb-sidebar-mode-btn').filter({ hasText: label }).click({
        timeout: 20000,
      })
      await page.waitForSelector(`.wb-sidebar-modes button.wb-sidebar-mode-btn--active`, { timeout: 8000 })
      await page.waitForTimeout(800)
    } catch {
      /* 模式切换失败仍截当前屏 */
    }
    return
  }
  if (prepare.startsWith('ai_store_tab:')) {
    const tabId = prepare.split(':')[1]
    const label = AI_STORE_TAB_LABELS[tabId]
    if (!label) return
    try {
      await page.locator('button.store-nav__item').filter({ hasText: label }).first().click({ timeout: 20000 })
      await page.waitForTimeout(1200)
    } catch {
      /* Tab 未渲染时仍截当前屏 */
    }
    return
  }
  if (prepare === 'filters_open') {
    try {
      await page.locator('.store-adv-toggle, button:has-text("高级筛选")').first().click({ timeout: 15000 })
      await page.waitForSelector('.store-adv-filters', { state: 'visible', timeout: 6000 })
      await page.waitForTimeout(600)
    } catch {
      /* 筛选面板未展开仍截图 */
    }
  }
}

async function applyPagePrepare(page, pageDef) {
  const raw = String(pageDef.prepare || '').trim()
  if (!raw) return
  for (const step of raw.split('|').map((s) => s.trim()).filter(Boolean)) {
    await applySinglePrepare(page, step)
  }
}

async function fetchMarketCatalogPages() {
  const skip = (process.env.SURFACE_AUDIT_SKIP_CATALOG || '0').trim().toLowerCase()
  if (['1', 'true', 'yes', 'on'].includes(skip)) return []
  const base = MARKET_BASE.replace(/\/$/, '')
  const out = []
  const seen = new Set()
  let offset = 0
  const limit = 200
  for (let page = 0; page < 20; page++) {
    const url = `${base}/api/market/catalog?limit=${limit}&offset=${offset}`
    let data
    try {
      const resp = await fetch(url, { headers: { Accept: 'application/json', 'User-Agent': 'xcagi-surface-audit/1.0' } })
      if (!resp.ok) break
      data = await resp.json()
    } catch {
      break
    }
    const items = Array.isArray(data?.items) ? data.items : []
    for (const item of items) {
      const cid = item?.id ?? item?.pkg_id
      if (cid == null) continue
      const key = String(cid)
      if (seen.has(key)) continue
      seen.add(key)
      const label = String(item.name || item.pkg_id || cid).trim()
      out.push({
        id: `catalog_${key.replace(/[^\w.-]+/g, '_')}`,
        name: `AI商品-${label}`,
        base: 'market',
        path: `/market/catalog/${cid}`,
      })
    }
    const total = Number(data?.total)
    offset += items.length
    if (!items.length || (Number.isFinite(total) && total > 0 && offset >= total)) break
    if (items.length < limit) break
  }
  return out
}

function expandPwMarketPages(staticPages, catalogPages) {
  if (!catalogPages.length) return staticPages
  const insertIdx = staticPages.findIndex((p) => p.id === 'market_orders')
  const at = insertIdx >= 0 ? insertIdx + 1 : staticPages.length
  return [...staticPages.slice(0, at), ...catalogPages, ...staticPages.slice(at)]
}

async function prepareAuditPage(page, pageDef, auditAuth) {
  if (pageDef.prepare) {
    await applyPagePrepare(page, pageDef)
  }
  if (isMarketAdminPage(pageDef)) {
    try {
      await page.waitForSelector('.wb-sidebar-admin-nav', { timeout: 12000 })
      const shortName = String(pageDef.name || '').replace(/^管理端·/, '')
      if (shortName) {
        await page.getByRole('heading', { name: shortName }).waitFor({ timeout: 8000 })
      }
    } catch {
      /* 侧栏已就绪即可截图 */
    }
    await page.waitForTimeout(600)
    return
  }
  if (pageDef.admin) {
    try {
      await page.waitForSelector(
        '#view-xcmax-admin, #view-server-functions, #view-automation-policy, #view-duty-roster-graph, #view-duty-time-architecture, .xcmax-admin-view, .server-functions-view',
        { timeout: 12000 },
      )
    } catch {
      /* 路由或权限未就绪时仍截当前屏 */
    }
    await page.waitForTimeout(600)
    return
  }
  if (pageDef.id !== 'lan_gate') return
  const bootstrap = (process.env.LAN_ADMIN_BOOTSTRAP_KEY || '').trim()
  if (bootstrap) {
    try {
      await page.request.post(`${FHD_BASE}/api/lan/activate`, {
        data: { key: bootstrap, device_label: 'SA 巡检' },
        headers: auditAuth?.csrf_token ? { 'X-CSRF-Token': auditAuth.csrf_token } : {},
      })
      await page.reload({ waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(800)
    } catch {
      /* 未启用 LAN 时走 UI 解锁 */
    }
  }
  try {
    await page.getByText('持有管理员密钥').click({ timeout: 4000 })
    await page.waitForTimeout(500)
  } catch {
    /* 已解锁或页面结构不同 */
  }
}

async function waitForEnterpriseAuditReady(page, laneCfg) {
  const sel = laneCfg.ready_selector || '.app-shell.is-ready, #app, body'
  try {
    await page.waitForSelector(sel, { timeout: laneCfg.ready_timeout_ms || 25000 })
  } catch {
    /* 部分页无 app-shell */
  }
  try {
    await page.waitForSelector('.app-shell.is-ready', { timeout: 12000 })
  } catch {
    /* 未登录或仍在 splash */
  }
  try {
    await page.waitForFunction(() => {
      const shell = document.querySelector('.app-shell.is-ready')
      const brand = document.querySelector('.sidebar-brand-text h4')?.textContent?.trim() || ''
      if (!shell || !brand) return false
      if (localStorage.getItem('xcagi_client_mods_ui_off') !== '1') return false
      return brand.includes('修茈') || brand.includes('企业') || brand.includes('XCAGI')
    }, { timeout: 15000 })
  } catch {
    /* 品牌文案未命中时仍继续 */
  }
  await page.waitForTimeout(800)
}

async function createAuditBrowserContext(browser, laneCfg, auditAuth, laneKey) {
  const context = await browser.newContext({
    viewport: laneCfg.viewport,
    deviceScaleFactor: laneCfg.device_scale_factor || 1,
    isMobile: !!laneCfg.is_mobile,
    hasTouch: !!laneCfg.has_touch,
    userAgent: laneCfg.user_agent,
    ignoreHTTPSErrors: true,
  })
  if (auditAuth) {
    await context.addCookies(playwrightCookies(auditAuth, '127.0.0.1'))
  }
  if (laneKey === 'P-S' || laneKey === 'P-App') {
    await context.addInitScript(ENTERPRISE_CLIENT_INIT_SCRIPT)
  }
  await context.addInitScript(buildAuthInitScript())
  return context
}

async function capturePsLaneShared(browser, pages, laneCfg, auditAuth, laneKey) {
  const context = await createAuditBrowserContext(browser, laneCfg, auditAuth, laneKey)
  const page = await context.newPage()
  const consoleErrors = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => consoleErrors.push(String(err)))

  const results = []
  try {
    const warmUrl = `${FHD_BASE}/?nosplash=1&full=1`
    await page.goto(warmUrl, { waitUntil: 'domcontentloaded', timeout: laneCfg.ready_timeout_ms || 30000 })
    await waitForEnterpriseAuditReady(page, laneCfg)

    for (let i = 0; i < pages.length; i++) {
      const pageDef = pages[i]
      const url = resolveUrl(pageDef, laneCfg)
      // 共享上下文：只归属本页新增的 console error，避免跨页滚雪球
      const errStart = consoleErrors.length
      let status = 0
      try {
        if (!url) {
          results.push({
            id: pageDef.id,
            name: pageDef.name,
            url: '',
            status: 0,
            error: '无 URL',
            analysis: ['无 URL'],
          })
          continue
        }
        if (i > 0) {
          const resp = await gotoWithRetry(page, url, laneCfg.ready_timeout_ms || 25000)
          status = resp ? resp.status() : 0
        } else {
          status = 200
        }
        await waitForEnterpriseAuditReady(page, laneCfg)
        await prepareAuditPage(page, pageDef, auditAuth)
        const shot = await page.screenshot({ type: 'png', fullPage: false })
        const saved = writeScreenshotPng(laneKey, i, pageDef, shot)
        results.push({
          id: pageDef.id,
          name: pageDef.name,
          android_route: pageDef.android_route || pageDef.id,
          url,
          status,
          native: !!pageDef.native,
          preview: !!pageDef.preview,
          admin: !!pageDef.admin,
          console_errors: consoleErrors.slice(errStart, errStart + 20),
          screenshot_saved: saved,
          analysis: [],
        })
      } catch (err) {
        let saved = ''
        try {
          const shot = await page.screenshot({ type: 'png', fullPage: false })
          saved = writeScreenshotPng(laneKey, i, pageDef, shot)
        } catch {
          /* 页面已不可用 */
        }
        results.push({
          id: pageDef.id,
          name: pageDef.name,
          url: url || '',
          status: status || 0,
          console_errors: [...consoleErrors.slice(errStart), String(err)].slice(0, 20),
          screenshot_saved: saved,
          error: String(err),
          analysis: [],
        })
      }
    }
  } finally {
    await context.close()
  }
  return results
}

async function waitForCjkFonts(page, timeoutMs = 30000) {
  for (const href of CJK_FONT_CSS) {
    try {
      await page.evaluate((url) => {
        if (document.querySelector('link[data-xcagi-audit-font]')) return
        const link = document.createElement('link')
        link.rel = 'stylesheet'
        link.href = url
        link.setAttribute('data-xcagi-audit-font', '1')
        document.head.appendChild(link)
      }, href)
      break
    } catch {
      /* try next mirror */
    }
  }
  try {
    await page.addStyleTag({
      content:
        '*{font-family:"Noto Sans SC","WenQuanYi Micro Hei","WenQuanYi Zen Hei","PingFang SC","Microsoft YaHei","SimHei",sans-serif!important}',
    })
  } catch {
    /* optional */
  }
  // 上限收紧：每页 networkidle ≤10s、字体轮询 ≤5s，否则 P-W 全量 60+ 页
  // 在 SURFACE_AUDIT_TIMEOUT_SEC 内跑不完（每页 context 独立、字体反复下载）
  try {
    await page.waitForLoadState('networkidle', { timeout: Math.min(timeoutMs, 10000) })
  } catch {
    /* SPA may never idle */
  }
  try {
    await page.evaluate(async () => {
      if (document.fonts && document.fonts.ready) await document.fonts.ready
      for (let i = 0; i < 20; i++) {
        if (document.fonts && document.fonts.check('16px "Noto Sans SC"')) return true
        await new Promise((r) => setTimeout(r, 250))
      }
      return false
    })
  } catch {
    /* fallback wait */
  }
  await page.waitForTimeout(1200)
}

function writeScreenshotPng(laneKey, pageIndex, pageDef, buffer) {
  const today = auditDateKey()
  const dir = path.join(FHD_ROOT, 'data/surface_audit/png', laneKey, today)
  fs.mkdirSync(dir, { recursive: true })
  const slug = `${String(pageIndex).padStart(3, '0')}_${pageDef.id || pageDef.name || 'page'}`.replace(/[^\w.-]+/g, '-')
  const filePath = path.join(dir, `${slug}.png`)
  fs.writeFileSync(filePath, buffer)
  return filePath
}

let _adminDigestPrepared = false

async function unlockAdminDigestOnPage(page, apiBase, auditAuth, opts = {}) {
  const marketAdmin = !!opts.marketAdmin
  const base = (apiBase || MARKETING_BASE).replace(/\/$/, '')
  let code = ''
  try {
    const identity = await fetchDigestIdentity(auditAuth, base)
    code = String(identity.code || '').trim().toUpperCase()
  } catch {
    return false
  }
  if (!code || !(await verifyAdminDigestCode(auditAuth, code, base))) {
    return false
  }
  await page.evaluate((digestCode) => {
    try {
      localStorage.setItem(
        'xcmax_digest_identity_code',
        JSON.stringify({ code: digestCode, ts: Date.now() }),
      )
    } catch {
      /* ignore */
    }
  }, code)
  try {
    const unlockBtn = page.getByRole('button', { name: /解锁管理端/ })
    if (await unlockBtn.isVisible({ timeout: 2500 })) {
      await unlockBtn.click()
      await page.waitForTimeout(1000)
    }
  } catch {
    /* 已解锁或无弹层 */
  }
  try {
    const adminReady = marketAdmin
      ? '.wb-sidebar-admin-nav, #app .app-shell'
      : '#view-xcmax-admin, #view-server-functions, #view-automation-policy, #view-duty-roster-graph, #view-duty-time-architecture, .xcmax-admin-view, .server-functions-view'
    await page.waitForSelector(adminReady, { timeout: 8000 })
    return true
  } catch {
    const errVisible = await page
      .locator('.nav-self-credit-dialog__err')
      .isVisible()
      .catch(() => false)
    return !errVisible
  }
}

async function ensureAdminDigestUnlock(auditAuth, context, apiBase) {
  if (_adminDigestPrepared) return
  _adminDigestPrepared = true
  const base = (apiBase || resolveAdminBase()).replace(/\/$/, '')
  let code = ''
  try {
    const identity = await fetchDigestIdentity(auditAuth, base)
    code = identity.code || ''
    if (code && !(await verifyAdminDigestCode(auditAuth, code, base))) {
      code = ''
    }
  } catch {
    /* 本地无 digest 接口时仍尝试 admin 会话截图 */
  }
  if (code) {
    await context.addInitScript((digestCode) => {
      try {
        localStorage.setItem('xcmax_digest_identity_code', JSON.stringify({ code: digestCode, ts: Date.now() }))
      } catch {
        /* ignore */
      }
    }, code)
  }
}

async function capturePage(browser, pageDef, laneCfg, auditAuth, laneKey, pageIndex) {
  const consoleErrors = []
  let url = resolveUrl(pageDef, laneCfg)
  const cookieHost = url ? cookieHostForUrl(url) : '127.0.0.1'
  const context = await browser.newContext({
    viewport: laneCfg.viewport,
    deviceScaleFactor: laneCfg.device_scale_factor || 1,
    isMobile: !!laneCfg.is_mobile,
    hasTouch: !!laneCfg.has_touch,
    userAgent: laneCfg.user_agent,
    ignoreHTTPSErrors: true,
  })
  if (auditAuth) {
    await context.addCookies(playwrightCookies(auditAuth, cookieHost))
  }
  if (pageDef.admin) {
    await ensureAdminDigestUnlock(auditAuth, context, MARKETING_BASE)
  }
  if (needsMarketAuth(pageDef, url) || isMarketAdminPage(pageDef)) {
    await injectMarketAuth(context, auditAuth)
  }
  if (needsEnterpriseClientInit(laneKey, pageDef)) {
    await context.addInitScript(ENTERPRISE_CLIENT_INIT_SCRIPT)
  }
  await context.addInitScript(buildAuthInitScript())
  const page = await context.newPage()
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => consoleErrors.push(String(err)))

  let status = 0
  try {
    if (pageDef.native || !url) {
      await page.setContent(nativePlaceholderHtml(pageDef, laneCfg.label || 'P-App'), {
        waitUntil: 'load',
      })
      status = 200
    } else {
      const resp = await gotoWithRetry(page, url, laneCfg.ready_timeout_ms || 25000)
      status = resp ? resp.status() : 0
      const sel = laneCfg.ready_selector || '#app'
      try {
        await page.waitForSelector(sel, { timeout: laneCfg.ready_timeout_ms || 25000 })
      } catch {
        /* 部分市场页无 app-shell */
      }
      if (isMarketAdminPage(pageDef)) {
        await waitForCjkFonts(page, laneCfg.ready_timeout_ms || 25000)
        const unlocked = await unlockAdminDigestOnPage(page, MARKETING_BASE, auditAuth, {
          marketAdmin: true,
        })
        if (!unlocked) {
          return {
            id: pageDef.id,
            name: pageDef.name,
            android_route: pageDef.android_route || pageDef.id,
            url: url || '',
            status,
            native: false,
            preview: !!pageDef.preview,
            admin: true,
            market_admin: true,
            digest_unlock_failed: true,
            console_errors: consoleErrors.slice(0, 20),
            analysis: ['管理端身份码解锁失败：须 xiu-ci.com 同源 digest 自签发 + modstore_token'],
          }
        }
      } else if (pageDef.base === 'marketing' || pageDef.base === 'market') {
        await waitForCjkFonts(page, laneCfg.ready_timeout_ms || 25000)
        if (pageDef.base === 'market') {
          try {
            await page.waitForSelector('#app, .app-shell, .store-nav, main', { timeout: 8000 })
            await page.waitForFunction(
              () => {
                const t = (document.body && document.body.innerText) || ''
                return t.replace(/\s+/g, '').length > 8
              },
              { timeout: 8000 },
            )
          } catch {
            /* SPA 未渲染完仍截图 */
          }
        }
      } else if (pageDef.admin) {
        await page.waitForTimeout(1200)
        const unlocked = await unlockAdminDigestOnPage(page, resolveAdminBase(), auditAuth)
        if (!unlocked) {
          return {
            id: pageDef.id,
            name: pageDef.name,
            android_route: pageDef.android_route || pageDef.id,
            url: url || '',
            status,
            native: false,
            preview: !!pageDef.preview,
            admin: true,
            digest_unlock_failed: true,
            console_errors: consoleErrors.slice(0, 20),
            analysis: [
              '管理端身份码解锁失败：须从 xiu-ci.com 同源拉码并校验；跨实例签发需配置 MODSTORE_DIGEST_PEER（见 .env.example）',
            ],
          }
        }
      } else {
        try {
          await page.waitForSelector('.app-shell.is-ready', { timeout: 12000 })
        } catch {
          /* 未登录或仍在 splash */
        }
        await page.waitForTimeout(800)
      }
      await prepareAuditPage(page, pageDef, auditAuth)
    }
    const shot = await page.screenshot({ type: 'png', fullPage: false })
    const saved = writeScreenshotPng(laneKey, pageIndex, pageDef, shot)
    return {
      id: pageDef.id,
      name: pageDef.name,
      android_route: pageDef.android_route || pageDef.id,
      url: url || `native://${pageDef.android_route || pageDef.id}`,
      status,
      native: !!pageDef.native,
      preview: !!pageDef.preview,
      admin: !!pageDef.admin,
      market_admin: isMarketAdminPage(pageDef),
      digest_unlock_ok: !!pageDef.admin,
      console_errors: consoleErrors.slice(0, 20),
      screenshot_saved: saved,
      analysis: [],
    }
  } catch (err) {
    let saved = ''
    try {
      const shot = await page.screenshot({ type: 'png', fullPage: false })
      saved = writeScreenshotPng(laneKey, pageIndex, pageDef, shot)
    } catch {
      /* 页面已不可用 */
    }
    return {
      id: pageDef.id,
      name: pageDef.name,
      android_route: pageDef.android_route || pageDef.id,
      url: url || '',
      status: status || 0,
      native: !!pageDef.native,
      console_errors: [...consoleErrors, String(err)].slice(0, 20),
      screenshot_saved: saved,
      screenshot_b64: '',
      error: String(err),
      analysis: [`截图失败: ${err}`],
    }
  } finally {
    await context.close()
  }
}

function mergeAndroidCaptures(webPages, androidPayload, laneCfg, laneKey) {
  if (!androidPayload?.pages?.length) return webPages
  const byId = new Map(androidPayload.pages.filter((p) => p.screenshot_b64).map((p) => [p.id, p]))
  return webPages.map((row, pageIndex) => {
    const shot = byId.get(row.id)
    if (!shot?.screenshot_b64) return row
    let screenshot_saved = row.screenshot_saved || ''
    try {
      screenshot_saved = writeScreenshotPng(
        laneKey,
        pageIndex,
        row,
        Buffer.from(shot.screenshot_b64, 'base64'),
      )
    } catch {
      screenshot_saved = ''
    }
    return {
      ...row,
      ...shot,
      url: shot.url || row.url,
      screenshot_saved,
      android_capture: true,
      analysis: shot.analysis || ['Android App adb 截图（SA 真机巡检）'],
    }
  })
}

function androidEnabled() {
  return process.env.SURFACE_AUDIT_ANDROID === '1' || process.env.XCAGI_SURFACE_AUDIT_ANDROID === '1'
}

function adbHasDevice() {
  const adbPath = path.join(FHD_ROOT, 'mobile-android/.toolchain/android-sdk/platform-tools/adb')
  const adbBin = fs.existsSync(adbPath) ? adbPath : 'adb'
  try {
    const proc = spawnSync(adbBin, ['devices'], { encoding: 'utf8', timeout: 8000 })
    return (proc.stdout || '')
      .split('\n')
      .slice(1)
      .some((line) => {
        const parts = line.trim().split(/\s+/)
        return parts.length >= 2 && parts[1] === 'device'
      })
  } catch {
    return false
  }
}

function ensureEnterpriseAuditEnv(laneCfg) {
  if (laneCfg?.product_sku === 'enterprise') {
    process.env.SURFACE_AUDIT_PRODUCT_SKU = 'enterprise'
    process.env.SURFACE_AUDIT_INCLUDE_ENTERPRISE = '1'
    process.env.SURFACE_AUDIT_ACCOUNT_KIND = 'enterprise'
    if (!process.env.SURFACE_AUDIT_USER) process.env.SURFACE_AUDIT_USER = 'xcagi-enterprise-demo'
    if (!process.env.SURFACE_AUDIT_PASSWORD) process.env.SURFACE_AUDIT_PASSWORD = 'Demo@2026'
  }
}

function tryAndroidCapture() {
  if (process.env.SURFACE_AUDIT_ANDROID !== '1' && process.env.XCAGI_SURFACE_AUDIT_ANDROID !== '1') {
    return null
  }
  const script = path.join(FHD_ROOT, 'scripts/ci/run_android_surface_audit.mjs')
  const tmp = path.join(FHD_ROOT, 'data/surface_audit/.android-merge.json')
  const proc = spawnSync('node', [script, '--out', tmp], {
    cwd: FHD_ROOT,
    env: process.env,
    encoding: 'utf8',
    maxBuffer: 4 * 1024 * 1024,
    timeout: Number(process.env.SURFACE_AUDIT_ANDROID_TIMEOUT_MS || '600000'),
  })
  if (fs.existsSync(tmp)) {
    try {
      return JSON.parse(fs.readFileSync(tmp, 'utf8'))
    } catch {
      /* fall through */
    }
  }
  if (proc.status !== 0) {
    return {
      success: false,
      message: (proc.stderr || proc.stdout || proc.error?.message || 'android 巡检失败').slice(0, 500),
    }
  }
  try {
    return JSON.parse(proc.stdout || '{}')
  } catch {
    return { success: false, message: 'android 巡检输出非 JSON' }
  }
}

function auditConcurrency() {
  const n = Number(process.env.SURFACE_AUDIT_CONCURRENCY || '4')
  if (!Number.isFinite(n) || n < 1) return 4
  return Math.min(12, Math.floor(n))
}

async function mapWithConcurrency(items, limit, fn) {
  const results = new Array(items.length)
  let cursor = 0
  async function worker() {
    while (true) {
      const i = cursor++
      if (i >= items.length) return
      results[i] = await fn(items[i], i)
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, () => worker()))
  return results
}

async function main() {
  _adminDigestPrepared = false
  const raw = fs.readFileSync(CONFIG_PATH, 'utf8')
  const cfg = JSON.parse(raw)
  const laneCfg = cfg.lanes[laneArg]
  if (!laneCfg) {
    console.error(JSON.stringify({ success: false, message: `未知 lane: ${laneArg}` }))
    process.exit(1)
  }
  if (laneCfg.product_sku) {
    process.env.SURFACE_AUDIT_PRODUCT_SKU = laneCfg.product_sku
    if (laneCfg.product_sku === 'enterprise') process.env.SURFACE_AUDIT_INCLUDE_ENTERPRISE = '1'
  }
  ensureEnterpriseAuditEnv(laneCfg)
  if (
    laneArg === 'P-App' &&
    !androidEnabled() &&
    adbHasDevice() &&
    process.env.SURFACE_AUDIT_ANDROID !== '0'
  ) {
    process.env.SURFACE_AUDIT_ANDROID = '1'
  }

  let pages = (laneCfg.pages || []).filter((p) => {
    if (laneArg === 'P-S' && (p.admin || p.base === 'admin')) return false
    if (p.sku === 'enterprise' && (process.env.SURFACE_AUDIT_PRODUCT_SKU || 'personal') === 'personal') {
      return process.env.SURFACE_AUDIT_INCLUDE_ENTERPRISE === '1'
    }
    return true
  })
  if (laneArg === 'P-W') {
    const catalogPages = await fetchMarketCatalogPages()
    pages = expandPwMarketPages(pages, catalogPages)
  }

  let merged = []
  let androidMeta = null
  let androidPayload = null

  let auditAuth = null
  try {
    auditAuth = await ensureAuditAuth()
  } catch (err) {
    console.error(JSON.stringify({ success: false, message: `巡检登录失败: ${err}` }))
    process.exit(1)
  }

  if (laneArg === 'P-App' && androidEnabled()) {
    androidPayload = tryAndroidCapture()
  }

  if (!merged.length) {
    const browser = await chromium.launch({ headless: true })
    let results = []
    try {
      if (laneArg === 'P-S') {
        results = await capturePsLaneShared(browser, pages, laneCfg, auditAuth, laneArg)
      } else {
        const conc = auditConcurrency()
        const rows = await mapWithConcurrency(pages, conc, async (pageDef, i) => {
          const row = await capturePage(browser, pageDef, laneCfg, auditAuth, laneArg, i)
          if (row?.digest_unlock_failed) return null
          row.analysis = analyzePage(row)
          return row
        })
        results = rows.filter(Boolean)
      }
    } finally {
      await browser.close()
    }
    if (laneArg === 'P-S') {
      for (const row of results) row.analysis = analyzePage(row)
    }
    merged = results
    if (laneArg === 'P-App' && !androidPayload) {
      androidPayload = tryAndroidCapture()
    }
    if (androidPayload?.pages?.length) {
      merged = mergeAndroidCaptures(merged, androidPayload, laneCfg, laneArg)
      androidMeta = {
        source: androidPayload.source,
        device_count: androidPayload.device_count,
        merged_count: merged.filter((p) => p.android_capture).length,
        message: androidPayload.message,
      }
    } else if (androidPayload && !androidPayload.success) {
      androidMeta = { message: androidPayload.message, hint: androidPayload.hint }
    }
  }

  const payload = {
    success: true,
    lane: laneArg,
    workflow_node: laneCfg.workflow_node,
    label: laneCfg.label,
    captured_at: new Date().toISOString(),
    base_url: FHD_BASE,
    market_base_url: MARKET_BASE,
    page_count: merged.length,
    pages: merged,
    android_audit: androidMeta,
    analysis_summary: merged.flatMap((p) => p.analysis.map((line) => `${p.name}: ${line}`)).slice(0, 40),
  }

  const text = JSON.stringify(payload)
  if (OUT_PATH) {
    fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true })
    fs.writeFileSync(OUT_PATH, text, 'utf8')
  }
  process.stdout.write(text)
}

main().catch((err) => {
  console.error(JSON.stringify({ success: false, message: String(err) }))
  process.exit(1)
})
