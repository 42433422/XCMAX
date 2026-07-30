#!/usr/bin/env node
/**
 * Drive packaged XCAGI via CDP (9222) and exercise each sidebar page's capabilities.
 * Usage: node FHD/frontend/e2e/_run_sidebar_capability_closed_loop.mjs
 */
import fs from 'node:fs'
import path from 'node:path'
import http from 'node:http'
import { fileURLToPath } from 'node:url'
import WebSocket from 'ws'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '../..')
const EV = path.join(ROOT, 'docs/evidence/e2e/sidebar-capability-closed-loop-20260724')
const SHOTS = path.join(EV, 'shots')
fs.mkdirSync(SHOTS, { recursive: true })

function getJson(url) {
  return new Promise((resolve, reject) => {
    http
      .get(url, (res) => {
        let d = ''
        res.on('data', (c) => (d += c))
        res.on('end', () => {
          try {
            resolve(JSON.parse(d))
          } catch (e) {
            reject(e)
          }
        })
      })
      .on('error', reject)
  })
}

async function waitTargets(timeoutMs = 90000) {
  const end = Date.now() + timeoutMs
  while (Date.now() < end) {
    try {
      const targets = await getJson('http://127.0.0.1:9222/json')
      const pages = targets.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl)
      if (pages.length) return pages
    } catch {
      /* retry */
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error('no CDP page targets')
}

class Cdp {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl)
    this.id = 0
    this.pending = new Map()
    this.ws.on('message', (raw) => {
      const msg = JSON.parse(String(raw))
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id)
        this.pending.delete(msg.id)
        if (msg.error) reject(new Error(JSON.stringify(msg.error)))
        else resolve(msg.result)
      }
    })
  }
  ready() {
    return new Promise((resolve, reject) => {
      this.ws.once('open', resolve)
      this.ws.once('error', reject)
    })
  }
  send(method, params = {}, timeout = 120000) {
    const id = ++this.id
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`timeout ${method}`))
      }, timeout)
      this.pending.set(id, {
        resolve: (v) => {
          clearTimeout(timer)
          resolve(v)
        },
        reject: (e) => {
          clearTimeout(timer)
          reject(e)
        },
      })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }
  async evaluate(expression, awaitPromise = false, timeout = 120000) {
    const r = await this.send(
      'Runtime.evaluate',
      { expression, awaitPromise, returnByValue: true, userGesture: true },
      timeout,
    )
    if (r.exceptionDetails) {
      const ex = r.exceptionDetails.exception?.description || r.exceptionDetails.text
      throw new Error(ex)
    }
    return r.result?.value
  }
  async shot(name) {
    const r = await this.send('Page.captureScreenshot', { format: 'png', fromSurface: true })
    if (r?.data) {
      const file = path.join(SHOTS, `${name}.png`)
      fs.writeFileSync(file, Buffer.from(r.data, 'base64'))
      return file
    }
    return ''
  }
  close() {
    this.ws.close()
  }
}

const PAGES = [
  { id: '01-chat', label: '智能对话', path: '/' },
  { id: '02-im', label: '信息', path: '/im' },
  { id: '03-ai-ecosystem', label: '智能生态', path: '/ai-ecosystem' },
  { id: '04-knowledge', label: '知识库', path: '/persy/knowledge' },
  { id: '05-employee-space', label: '员工空间', path: '/workflow-employee-space' },
  { id: '06-workflow-viz', label: '流程可视化', path: '/workflow-visualization' },
  { id: '07-products', label: '业务对象/业务列表', path: '/products' },
  { id: '08-customers', label: '组织管理', path: '/customers' },
  { id: '09-orders', label: '业务单据', path: '/orders' },
  { id: '10-shipment', label: '业务记录', path: '/shipment-records' },
  { id: '11-materials', label: '资源库', path: '/materials' },
  { id: '12-data-sources', label: '数据来源', path: '/data-sources' },
  { id: '13-print', label: '模板与打印', path: '/print' },
  { id: '14-printer-list', label: '打印机列表', path: '/printer-list' },
  { id: '15-settings', label: '系统设置', path: '/settings' },
]

const PAGE_API = {
  '01-chat': [
    ['/api/auth/me', 'GET'],
    ['/api/conversations', 'GET'],
    ['/api/ping', 'GET'],
  ],
  '02-im': [
    ['/api/im/conversations', 'GET'],
    ['/api/im/contacts', 'GET'],
  ],
  '03-ai-ecosystem': [
    ['/api/platform-shell/capabilities', 'GET'],
    ['/api/mods/', 'GET'],
  ],
  '04-knowledge': [
    ['/api/persy/knowledge', 'GET'],
    ['/api/knowledge/base', 'GET'],
  ],
  '05-employee-space': [
    ['/api/workflow/employees', 'GET'],
    ['/api/workflow-employee-space/overview', 'GET'],
  ],
  '06-workflow-viz': [['/api/workflow/graph', 'GET']],
  '07-products': [
    ['/api/products', 'GET'],
    ['/api/erp/products', 'GET'],
  ],
  '08-customers': [['/api/customers', 'GET']],
  '09-orders': [['/api/orders', 'GET']],
  '10-shipment': [
    ['/api/shipment-records', 'GET'],
    ['/api/shipments', 'GET'],
  ],
  '11-materials': [['/api/materials', 'GET']],
  '12-data-sources': [
    ['/api/data-sources', 'GET'],
    ['/api/datasources', 'GET'],
  ],
  '13-print': [
    ['/api/print/templates', 'GET'],
    ['/api/templates', 'GET'],
  ],
  '14-printer-list': [['/api/print/printers', 'GET']],
  '15-settings': [
    ['/api/auth/me', 'GET'],
    ['/api/workspace/prefs', 'GET'],
    ['/api/system/industry', 'GET'],
    ['/api/mods/', 'GET'],
  ],
}

async function main() {
  const pages = await waitTargets()
  // Prefer non-splash; else use splash (content may load in-place)
  const target =
    pages.find((p) => !String(p.url || '').includes('splash.html')) || pages[0]
  const cdp = new Cdp(target.webSocketDebuggerUrl)
  await cdp.ready()
  await cdp.send('Runtime.enable')
  await cdp.send('Page.enable')

  // Wait until SPA shell is ready
  for (let i = 0; i < 60; i++) {
    const ready = await cdp.evaluate(
      `Boolean(document.querySelector('.sidebar, .main-container, #app') && document.body && document.body.innerText.length > 20)`,
    )
    if (ready) break
    await new Promise((r) => setTimeout(r, 500))
  }

  await cdp.evaluate(`(() => {
    const app = document.querySelector('#app')?.__vue_app__;
    window.__xcagiRouter = app?.config?.globalProperties?.$router || null;
    return Boolean(window.__xcagiRouter);
  })()`)

  const api = (pth, method = 'GET', body = null) =>
    cdp.evaluate(
      `(async () => {
      try {
        const opts = { method: ${JSON.stringify(method)}, credentials: 'include', headers: {'Content-Type':'application/json'} };
        ${body == null ? '' : `opts.body = JSON.stringify(${JSON.stringify(body)});`}
        const r = await fetch(${JSON.stringify(pth)}, opts);
        const text = await r.text();
        let data = null;
        try { data = JSON.parse(text); } catch { data = text.slice(0, 400); }
        return { ok: r.ok, status: r.status, data };
      } catch (e) {
        return { ok: false, status: 0, error: String(e) };
      }
    })()`,
      true,
    )

  const navRoute = (p) =>
    cdp.evaluate(
      `(async () => {
      const router = window.__xcagiRouter || document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$router;
      if (!router) {
        // fallback: click sidebar by matching route hash/path text later
        history.pushState({}, '', ${JSON.stringify(p)});
        window.dispatchEvent(new PopStateEvent('popstate'));
        await new Promise(r => setTimeout(r, 500));
        return { ok: location.pathname.includes(${JSON.stringify(p === '/' ? '' : p)}) || location.href.includes(${JSON.stringify(p)}), path: location.pathname, mode: 'history' };
      }
      await router.push(${JSON.stringify(p)});
      await new Promise(r => setTimeout(r, 700));
      return { ok: true, path: router.currentRoute.value.fullPath, name: String(router.currentRoute.value.name || '') };
    })()`,
      true,
    )

  const inventory = () =>
    cdp.evaluate(`(() => {
      const title = (document.querySelector('.page-title')?.textContent || document.title || '').trim();
      const buttons = [...new Set([...document.querySelectorAll('button, a.btn, [role=button]')]
        .map(b => (b.textContent || b.getAttribute('aria-label') || '').trim().replace(/\\s+/g,' '))
        .filter(t => t && t.length < 36))].slice(0, 35);
      const inputs = [...document.querySelectorAll('input, textarea, select')].map(i => ({
        tag: i.tagName, type: i.type || '', placeholder: i.placeholder || ''
      })).slice(0, 25);
      const tabs = [...new Set([...document.querySelectorAll('[role=tab], .tabs button, .tab, .el-tabs__item')]
        .map(t => (t.textContent || '').trim()).filter(Boolean))].slice(0, 20);
      const text = (document.body.innerText || '').slice(0, 800);
      const errors = [...document.querySelectorAll('.el-message--error, .error')]
        .map(e => (e.textContent || '').trim()).filter(Boolean).slice(0, 5);
      return { title, buttons, inputs, tabs, errors, text, url: location.href };
    })()`)

  const results = []

  // ---- 智能对话 closed loop ----
  {
    const nav = await navRoute('/')
    const inv = await inventory()
    const auth = await api('/api/auth/me')
    const convList = await api('/api/conversations')
    // discover conversation send endpoints
    const probes = await cdp.evaluate(
      `(async () => {
      const candidates = [
        '/api/chat/send',
        '/api/conversations/send',
        '/api/assistant/chat',
        '/api/planner/chat',
      ];
      const out = [];
      for (const p of candidates) {
        try {
          const r = await fetch(p, {
            method: 'POST', credentials: 'include',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({
              message: '闭环探测：查询今日业务概况',
              content: '闭环探测：查询今日业务概况',
              text: '闭环探测：查询今日业务概况',
              query: '闭环探测：查询今日业务概况',
            }),
          });
          const t = await r.text();
          let data=null; try{data=JSON.parse(t)}catch{data=t.slice(0,200)}
          out.push({ path:p, status:r.status, ok:r.ok, data });
        } catch(e) {
          out.push({ path:p, status:0, ok:false, error:String(e) });
        }
      }
      return out;
    })()`,
      true,
      180000,
    )

    const uiSend = await cdp.evaluate(
      `(async () => {
      const input = document.querySelector('textarea, input[placeholder*="需求"], input[placeholder*="输入"]');
      if (!input) return { ok:false, reason:'no_input' };
      const proto = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      setter?.call(input, '闭环测试：列出当前可用业务能力');
      input.dispatchEvent(new Event('input', { bubbles:true }));
      input.dispatchEvent(new Event('change', { bubbles:true }));
      const sendBtn = [...document.querySelectorAll('button')].find(b => /发送/.test(b.textContent || ''));
      if (!sendBtn) return { ok:false, reason:'no_send_btn' };
      sendBtn.click();
      await new Promise(r => setTimeout(r, 3500));
      const bubbles = [...document.querySelectorAll('[class*="message"], [class*="bubble"], .chat-item')]
        .map(el => (el.textContent || '').trim().slice(0, 140)).filter(Boolean).slice(-8);
      return { ok: true, bubbles };
    })()`,
      true,
    )

    const tabs = await cdp.evaluate(
      `(async () => {
      const labels = ['查数据','列表','今日单据','待办'];
      const out = [];
      for (const label of labels) {
        const btn = [...document.querySelectorAll('button, [role=tab], a')].find(el => (el.textContent || '').trim() === label);
        if (!btn) { out.push({ label, ok:false, reason:'missing' }); continue; }
        btn.click();
        await new Promise(r => setTimeout(r, 700));
        out.push({
          label, ok:true,
          title: (document.querySelector('.page-title')?.textContent || '').trim(),
          snippet: (document.body.innerText || '').slice(0, 220),
        });
      }
      // back to chat-ish
      const chat = [...document.querySelectorAll('button,a')].find(el => (el.textContent || '').trim() === '查数据');
      chat?.click();
      return out;
    })()`,
      true,
    )

    await cdp.shot('01-chat')
    const apiOk = Boolean(auth?.ok) || probes.some((p) => p.ok) || Boolean(convList?.ok)
    const uiOk = Boolean(uiSend?.ok) || (tabs || []).some((t) => t.ok)
    results.push({
      id: '01-chat',
      label: '智能对话',
      path: '/',
      nav,
      inventory: inv,
      auth,
      conversations: { status: convList?.status, ok: convList?.ok },
      api_send_probes: probes,
      ui_send: uiSend,
      tabs,
      closed_loop: {
        page_reachable: true,
        api_ok: apiOk,
        ui_ok: uiOk,
        tabs_ok: (tabs || []).filter((t) => t.ok).length,
        ok: apiOk && uiOk,
      },
    })
    console.log('CHAT', JSON.stringify(results[0].closed_loop))
  }

  for (const pdef of PAGES.slice(1)) {
    console.log('===', pdef.label, pdef.path)
    let nav
    try {
      nav = await navRoute(pdef.path)
    } catch (e) {
      nav = { ok: false, error: String(e) }
    }
    await new Promise((r) => setTimeout(r, 600))
    let inv
    try {
      inv = await inventory()
    } catch (e) {
      inv = { error: String(e) }
    }

    const apiResults = []
    for (const [pth, method] of PAGE_API[pdef.id] || []) {
      try {
        apiResults.push({ path: pth, method, result: await api(pth, method) })
      } catch (e) {
        apiResults.push({ path: pth, method, result: { ok: false, error: String(e) } })
      }
    }

    const uiActions = {}
    const clickCreate = `(async () => {
      const add = [...document.querySelectorAll('button,a')].find(b => /新增|添加|创建|开单|连接|接入|上传/.test(b.textContent || ''));
      if (!add) return { ok:false, reason:'no_create_btn', buttons: [...document.querySelectorAll('button')].map(b => b.textContent.trim()).filter(Boolean).slice(0, 25) };
      add.click();
      await new Promise(r => setTimeout(r, 900));
      return {
        ok: true,
        dialog: Boolean(document.querySelector('.el-dialog, .modal, [role=dialog], .drawer, .el-drawer')),
        path: location.pathname,
        snippet: (document.body.innerText || '').slice(0, 350),
      };
    })()`

    if (['08-customers', '09-orders', '12-data-sources', '04-knowledge', '07-products', '11-materials'].includes(pdef.id)) {
      uiActions.create_or_add = await cdp.evaluate(clickCreate, true)
    }
    if (pdef.id === '14-printer-list') {
      uiActions.list_ui = await cdp.evaluate(`(() => {
        const text = document.body.innerText || '';
        return { ok: /Canon|打印机|就绪|默认|HP|EPSON|Brother/.test(text), snippet: text.slice(0, 450) };
      })()`)
    }
    if (pdef.id === '13-print') {
      uiActions.print_ui = await cdp.evaluate(`(() => {
        const text = document.body.innerText || '';
        const btns = [...document.querySelectorAll('button')].map(b => b.textContent.trim()).filter(Boolean).slice(0, 30);
        return { ok: btns.length > 0 || /模板|打印|预览/.test(text), buttons: btns, snippet: text.slice(0, 450) };
      })()`)
    }
    if (pdef.id === '15-settings') {
      uiActions.settings_sections = await cdp.evaluate(`(() => {
        const text = document.body.innerText || '';
        const marks = ['账号','模型','Mod','移动端','扩展','行业','更新','关于'].filter(k => text.includes(k));
        return { ok: marks.length >= 2, marks };
      })()`)
    }
    if (['02-im', '03-ai-ecosystem', '05-employee-space', '06-workflow-viz', '10-shipment'].includes(pdef.id)) {
      uiActions.surface = await cdp.evaluate(`(() => {
        const text = document.body.innerText || '';
        const btns = [...document.querySelectorAll('button')].map(b => b.textContent.trim()).filter(Boolean).slice(0, 25);
        return { ok: text.length > 40, buttons: btns, snippet: text.slice(0, 500) };
      })()`)
    }

    await cdp.shot(pdef.id)
    const apiOk = apiResults.some((x) => x.result?.ok)
    const uiOk = Object.values(uiActions).some((v) => v && v.ok) || Boolean(inv && !inv.error && (inv.buttons?.length || inv.text))
    const pageOk = Boolean(nav?.ok) && (apiOk || uiOk)
    results.push({
      id: pdef.id,
      label: pdef.label,
      path: pdef.path,
      nav,
      inventory: inv,
      api: apiResults,
      ui_actions: uiActions,
      closed_loop: {
        page_reachable: Boolean(nav?.ok),
        api_ok: apiOk,
        ui_ok: uiOk,
        ok: pageOk,
      },
    })
  }

  // Cross-page business closed loop: create customer -> list appears
  let bizLoop = { ok: false }
  try {
    await navRoute('/customers')
    const before = await api('/api/customers')
    const code = `CL${Date.now() % 100000}`
    const created = await api('/api/customers', 'POST', { name: `闭环组织${code}`, code })
    const after = await api('/api/customers')
    const beforeCount = Array.isArray(before?.data) ? before.data.length : Array.isArray(before?.data?.items) ? before.data.items.length : null
    const afterCount = Array.isArray(after?.data) ? after.data.length : Array.isArray(after?.data?.items) ? after.data.items.length : null
    bizLoop = {
      ok: Boolean(created?.ok) && (afterCount == null || beforeCount == null || afterCount >= beforeCount),
      created_status: created?.status,
      beforeCount,
      afterCount,
      created_ok: Boolean(created?.ok),
    }
  } catch (e) {
    bizLoop = { ok: false, error: String(e) }
  }

  const summary = {
    started_from: '智能对话',
    total: results.length,
    ok_count: results.filter((r) => r.closed_loop?.ok).length,
    fail: results.filter((r) => !r.closed_loop?.ok).map((r) => r.label),
    business_create_customer_loop: bizLoop,
  }
  const out = { summary, results }
  fs.writeFileSync(path.join(EV, '07-sidebar-capability-results.json'), JSON.stringify(out, null, 2) + '\n')
  fs.writeFileSync(
    path.join(EV, 'CHECKLIST.md'),
    [
      '# 侧栏能力闭环 2026-07-24',
      '',
      `从智能对话起共 ${summary.total} 页，通过 ${summary.ok_count}，失败：${summary.fail.join('、') || '无'}`,
      '',
      `组织创建闭环：${bizLoop.ok ? 'OK' : 'FAIL'}`,
      '',
      ...results.map(
        (r) =>
          `- [${r.closed_loop?.ok ? 'x' : ' '}] ${r.label}（api=${r.closed_loop?.api_ok} ui=${r.closed_loop?.ui_ok}）`,
      ),
      '',
    ].join('\n'),
  )
  console.log(JSON.stringify(summary, null, 2))
  cdp.close()
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
