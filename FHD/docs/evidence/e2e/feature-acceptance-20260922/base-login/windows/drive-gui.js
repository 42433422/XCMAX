// drive-gui.js - drive the real XCAGI desktop app (Electron, CDP) on Windows for the
// base-login acceptance round: login via real input events, screenshot, logout via the
// real UI, screenshot again. Node 22 (global WebSocket + fetch).
//
// Usage: node drive-gui.js <outDir>
//   env: XCAGI_TEST_USER (default SUNBIRD), XCAGI_TEST_PASS (required), CDP_PORT (default 9222)
//
// Writes: <outDir>/shot/W2-login-page.png, W2-login-workspace.png, W4-login-page-again.png
//         <outDir>/log/gui-drive.json  (step-by-step diagnostics)

const fs = require('fs')
const path = require('path')

const OUT = process.argv[2] || '.'
const PORT = process.env.CDP_PORT || '9222'
const USER = process.env.XCAGI_TEST_USER || 'SUNBIRD'
const PASS = process.env.XCAGI_TEST_PASS || ''
const SHOT_DIR = path.join(OUT, 'shot')
const LOG_DIR = path.join(OUT, 'log')
fs.mkdirSync(SHOT_DIR, { recursive: true })
fs.mkdirSync(LOG_DIR, { recursive: true })

const STEPS = []
function note(name, value) {
  STEPS.push({ at: new Date().toISOString(), step: name, value })
  console.log('[' + name + '] ' + JSON.stringify(value))
}
const sleep = ms => new Promise(r => setTimeout(r, ms))

async function pageTarget(timeoutMs = 120000) {
  const end = Date.now() + timeoutMs
  while (Date.now() < end) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json`)
      const list = await res.json()
      const t = list.find(x => x.type === 'page' && x.webSocketDebuggerUrl)
      if (t) return t
    } catch (e) { /* app still starting */ }
    await sleep(2000)
  }
  throw new Error('no CDP page target on port ' + PORT)
}

let ws, msgId = 0
const pending = new Map()
function send(method, params = {}, timeoutMs = 60000) {
  const id = ++msgId
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('timeout: ' + method)) }, timeoutMs)
    pending.set(id, { resolve, reject, timer })
    ws.send(JSON.stringify({ id, method, params }))
  })
}

async function connect(target) {
  ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = e => rej(new Error('ws error')) })
  ws.onmessage = ev => {
    let m
    try { m = JSON.parse(ev.data) } catch { return }
    const p = pending.get(m.id)
    if (!p) return
    clearTimeout(p.timer); pending.delete(m.id)
    if (m.error) p.reject(new Error(m.error.message)); else p.resolve(m.result)
  }
}

async function evalJs(expr, timeoutMs = 60000) {
  const r = await send('Runtime.evaluate', {
    expression: expr, returnByValue: true, awaitPromise: true, timeout: timeoutMs,
  }, timeoutMs + 15000)
  if (r.exceptionDetails) throw new Error('JS: ' + JSON.stringify(r.exceptionDetails).slice(0, 300))
  return r.result && r.result.value
}

async function shot(name) {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  const p = path.join(SHOT_DIR, name)
  fs.writeFileSync(p, Buffer.from(r.data, 'base64'))
  note('screenshot', { file: name, bytes: fs.statSync(p).size })
  return p
}

const FINDER = (text, tag) => `Array.from(document.querySelectorAll(${JSON.stringify(tag)}))`
  + `.find(e => e.offsetParent !== null && (e.textContent||'').replace(/\\s+/g,'') === ${JSON.stringify(String(text).replace(/\s+/g, ''))})`

async function rectOf(finder) {
  return evalJs(`(() => { const el = (${finder}); if (!el) return null;
    const r = el.getBoundingClientRect(); if (!r.width && !r.height) return null;
    return {x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height,
            text: (el.textContent||el.value||'').trim().slice(0,60)}; })()`)
}

async function clickFinder(finder, label, waitMs = 900) {
  const r = await rectOf(finder)
  if (!r) throw new Error('element not found: ' + label)
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: r.x, y: r.y, button: 'none' })
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: r.x, y: r.y, button: 'left', clickCount: 1 })
  await sleep(60)
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: r.x, y: r.y, button: 'left', clickCount: 1 })
  await sleep(waitMs)
  note('click', { label, rect: r })
  return r
}

async function clickText(text, tag = 'button') {
  const f = FINDER(text, tag)
  const end = Date.now() + 30000
  while (Date.now() < end) {
    if (await rectOf(f)) break
    await sleep(700)
  }
  return clickFinder(f, text)
}

async function typeInto(selector, text) {
  const ok = await evalJs(`(() => { const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return false; el.focus(); return document.activeElement === el; })()`)
  if (!ok) throw new Error('cannot focus ' + selector)
  await send('Input.insertText', { text })
  await sleep(400)
  note('type', { selector, length: String(text).length })
}

function domSnapshot() {
  return evalJs(`(() => {
    const inputs = Array.from(document.querySelectorAll('input')).filter(e => e.offsetParent !== null)
      .map(e => ({ name: e.name, type: e.type, ph: e.placeholder }));
    const btns = Array.from(document.querySelectorAll('button')).filter(e => e.offsetParent !== null)
      .map(e => (e.textContent||'').trim()).filter(Boolean).slice(0, 25);
    return { url: location.href, title: document.title, inputs, buttons: btns,
             body: (document.body.innerText || '').replace(/\\s+/g,' ').slice(0, 400) }; })()`)
}

async function waitFor(expr, timeoutMs, label) {
  const end = Date.now() + timeoutMs
  while (Date.now() < end) {
    try { if (await evalJs(expr)) return true } catch (e) { /* keep waiting */ }
    await sleep(1500)
  }
  throw new Error('waitFor timed out: ' + label)
}

async function main() {
  if (!PASS) throw new Error('XCAGI_TEST_PASS not set')
  const target = await pageTarget()
  await connect(target)
  await send('Page.enable')
  await send('Runtime.enable')
  note('connected', { url: target.url, title: target.title })

  // 1) login page
  await waitFor(`!!document.querySelector('input[name=username]')`, 120000, 'login form')
  await shot('W2-login-page.png')
  note('dom-login-page', await domSnapshot())

  // 2) real typing + click
  await typeInto('input[name=username]', USER)
  await typeInto('input[name=password]', PASS)
  await clickText('登录', 'button')

  // 3) workspace
  await waitFor(`location.href.indexOf('/login') === -1`, 180000, 'leave login page')
  await sleep(6000)
  await shot('W2-login-workspace.png')
  note('dom-workspace', await domSnapshot())

  // 4) GUI logout: settings -> logout -> confirm
  try {
    await clickText('系统设置', '*')
  } catch (e) {
    note('logout-nav-miss', { error: String(e.message), dom: await domSnapshot() })
  }
  await sleep(2500)
  try {
    await clickText('退出登录', '*')
    await sleep(1500)
    await clickText('确定', 'button')
    await sleep(4000)
  } catch (e) {
    note('logout-click-miss', { error: String(e.message), dom: await domSnapshot() })
  }

  const after = await domSnapshot()
  note('dom-after-logout', after)
  await shot('W4-login-page-again.png')
  const backToLogin = after.url.indexOf('/login') !== -1
    || await evalJs(`!!document.querySelector('input[name=password]')`)
  note('logout-result', { backToLogin: !!backToLogin, url: after.url })

  fs.writeFileSync(path.join(LOG_DIR, 'gui-drive.json'),
    JSON.stringify({ platform: 'windows', steps: STEPS, logoutBackToLogin: !!backToLogin }, null, 2))
  console.log('GUI DRIVE DONE; backToLogin=' + !!backToLogin)
}

main().then(() => process.exit(0)).catch(async err => {
  note('fatal', { error: String(err && err.message || err) })
  try { await shot('gui-drive-failure.png') } catch (e) { /* ignore */ }
  try { fs.writeFileSync(path.join(LOG_DIR, 'gui-drive.json'), JSON.stringify({ platform: 'windows', steps: STEPS }, null, 2)) } catch (e) { /* ignore */ }
  console.error('GUI DRIVE FAILED: ' + err)
  process.exit(1)
})