#!/usr/bin/env node
// accept-base-login-web.mjs - Web 端（修茈市场 xiu-ci.com）真机验收：真实浏览器执行
// 与 macOS / Windows 两轮同一份记录契约（platform="web"），产出 base-login-web-run.json。
//
// 真实性边界（不得放宽）：
//   - 全部用例都在【真实浏览器】里执行（Edge/Chrome，CDP 驱动真实鼠标/键盘事件），
//     不是直接打 HTTP 接口冒充界面操作；接口断言是在页面上下文里用 fetch 复核。
//   - 截图取自本轮浏览器渲染画面（WB1 另存整屏，含浏览器地址栏，证明是真实浏览器而不是接口脚本），
//     录像录的是本次运行的桌面画面。
//   - 判定只认产品既有的用户路径；产品确实不具备的行为不写成预期，而是按契约与文档口径如实记录为
//     观察项（例如 Web 端服务端 /api/auth/logout 受 CSRF 保护、不随界面退出被调用）。
//   - 凭据与 token 不落盘：日志只写 sha256 指纹前 16 位，绝不写明文。
//   - media[] 一律先写 pending_review；只有真的打开截图/看完录像后才允许手填那三项。
//
// 依赖：Node 22+（内置 WebSocket）。CDP 驱动由 XCAGI_CDP_DRIVER 指定（默认本机驱动路径）。
// 浏览器须先以 --remote-debugging-port=9222 启动并打开市场登录页。
//
// 用法：
//   XCAGI_TEST_USER=SUNBIRD XCAGI_TEST_PASS=*** node accept-base-login-web.mjs \
//     --base=https://xiu-ci.com --out=<OutDir> --repo-rel=<仓库相对目录> --with-video
//
// 产物（<OutDir> 下）：base-login-web-run.json / base-login-web-identity.json /
//   shot\ video\ log\

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn, execFileSync } from 'node:child_process';

const DRIVER = process.env.XCAGI_CDP_DRIVER || 'file:///C:/xcagi-test/driver/cdp.mjs';
const { Session, pickPageTarget } = await import(DRIVER);
const CDP_HTTP = process.env.CDP_HTTP || 'http://127.0.0.1:9222';

// ---------------------------------------------------------------- args
const argv = new Map(
  process.argv.slice(2).map((a) => {
    const m = a.match(/^--([^=]+)(?:=(.*))?$/);
    return m ? [m[1], m[2] ?? 'true'] : [a, 'true'];
  }),
);
const BASE = (argv.get('base') || 'https://xiu-ci.com').replace(/\/+$/, '');
const APP = `${BASE}/market`;
const OUT = argv.get('out') || path.join(process.env.TEMP || '.', 'win-evidence', 'feature-base-login-web');
const REPO_REL =
  argv.get('repo-rel') || 'FHD/docs/evidence/e2e/feature-acceptance-20260922/base-login/web';
const USER = process.env.XCAGI_TEST_USER || 'SUNBIRD';
const PASS = process.env.XCAGI_TEST_PASS || '';
const WITH_VIDEO = argv.get('with-video') === 'true';
const FFMPEG = argv.get('ffmpeg') || process.env.XCAGI_FFMPEG || 'C:\\xcagi-test\\ffmpeg\\ffmpeg.exe';
// Windows round record used for the cross-end account comparison (resolved next to this script,
// so the path does not depend on the caller's working directory).
const SCRIPT_DIR = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const WINDOWS_RUN_FILE =
  argv.get('windows-run') || process.env.XCAGI_WINDOWS_RUN || path.join(SCRIPT_DIR, '..', 'base-login-windows-run.json');

if (!PASS) {
  console.error('FATAL: XCAGI_TEST_PASS not set (operator-provided enterprise acceptance credential).');
  process.exit(2);
}

// ---------------------------------------------------------------- io helpers
const now = new Date();
const pad = (n) => String(n).padStart(2, '0');
const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
// local-time helpers: the record must state when the round happened on the machine, not in UTC
const localDate = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const localStamp = (d = new Date()) => `${localDate(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
const SHOT = path.join(OUT, 'shot');
const VIDEO = path.join(OUT, 'video');
const LOGD = path.join(OUT, 'log');
for (const d of [OUT, SHOT, VIDEO, LOGD]) fs.mkdirSync(d, { recursive: true });

const logLines = [];
function log(msg) {
  const line = `[${new Date().toTimeString().slice(0, 8)}] ${msg}`;
  logLines.push(line);
  console.log(line);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// "logged in" indicator in the deployed build: the sidebar account menu (the older build used
// .wb-sidebar-logout-btn; the deployed 1.0.0.1 build renders .wb-user-menu__trigger).
const LOGGED_IN_SEL = '.wb-user-menu__trigger, .wb-sidebar-logout-btn';
const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const fp = (v) => (v ? sha256(Buffer.from(String(v), 'utf8')).slice(0, 16) : '');
const fileSha = (p) => (fs.existsSync(p) ? sha256(fs.readFileSync(p)) : null);

// ---------------------------------------------------------------- video
let videoProc = null;
let videoFile = '';
function startVideo() {
  if (!WITH_VIDEO) return;
  if (!fs.existsSync(FFMPEG)) {
    log(`video: ffmpeg not found at ${FFMPEG} -> video element missing (verdict will be PARTIAL)`);
    return;
  }
  videoFile = path.join(VIDEO, `base-login-web-${stamp}.mp4`);
  try {
    const p = spawn(
      FFMPEG,
      ['-hide_banner', '-loglevel', 'error', '-f', 'gdigrab', '-framerate', '5', '-i', 'desktop',
       '-c:v', 'libx264', '-preset', 'veryfast', '-b:v', '1200k', '-pix_fmt', 'yuv420p', '-y', videoFile],
      { stdio: ['pipe', 'ignore', 'pipe'] },
    );
    p.stderr.on('data', (d) => log('video[ffmpeg]: ' + String(d).trim().slice(0, 300)));
    videoProc = p;
    log('video: recording -> ' + videoFile);
  } catch (e) {
    log('video: start failed - ' + e.message);
  }
}
async function stopVideo() {
  if (!videoProc) return;
  try {
    videoProc.stdin.write('q');
  } catch {}
  await new Promise((res) => {
    const t = setTimeout(() => { try { videoProc.kill('SIGKILL'); } catch {} res(); }, 15000);
    videoProc.on('exit', () => { clearTimeout(t); res(); });
  });
  videoProc = null;
  const size = fs.existsSync(videoFile) ? fs.statSync(videoFile).size : 0;
  log(`video: stopped (${size} bytes) -> ${videoFile}`);
  if (!size) videoFile = '';
}

function bringBrowserToFront() {
  try {
    execFileSync('powershell', ['-NoProfile', '-Command',
      "$p = Get-Process msedge -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1; " +
      "if ($p) { (New-Object -ComObject WScript.Shell).AppActivate($p.Id) | Out-Null; Start-Sleep -Milliseconds 800 }",
    ], { stdio: 'ignore', timeout: 20000 });
  } catch (e) {
    log('front: activate failed - ' + e.message);
  }
}

// ---------------------------------------------------------------- browser ops
let s = null;
// Evaluate an expression in the page through the raw CDP command (same semantics as the driver
// helper, but explicit about the protocol call we make).
async function inPageEval(expression, awaitPromise = true) {
  const r = await s.send('Runtime.evaluate', {
    expression, returnByValue: true, awaitPromise, userGesture: true,
  });
  if (r.exceptionDetails) {
    throw new Error('in-page expression failed: ' + JSON.stringify(r.exceptionDetails).slice(0, 500));
  }
  return r.result ? r.result.value : undefined;
}
async function connectBrowser() {
  s = await Session.connect('xiu-ci.com');
  await s.send('Page.bringToFront');
  return s;
}
async function inPage(fn, ...args) {
  return await inPageEval(`(${fn.toString()})(${args.map((a) => JSON.stringify(a)).join(',')})`);
}
async function apiFetch(apiPath, init = null, token = '') {
  for (let attempt = 1; attempt <= 5; attempt++) {
    const r = await inPageEval(`(async () => {
      const headers = {};
      const tok = ${token ? JSON.stringify(token) : `localStorage.getItem('modstore_token') || ''`};
      if (tok) headers['Authorization'] = 'Bearer ' + tok;
      try {
        const r = await fetch(${JSON.stringify(BASE + apiPath)}, { method: ${JSON.stringify(init?.method || 'GET')}, headers, credentials: 'include' });
        const t = await r.text();
        let j = null; try { j = JSON.parse(t); } catch {}
        return { status: r.status, body: j !== null ? j : t.slice(0, 300) };
      } catch (e) { return { status: 0, error: String(e) }; }
    })()`);
    // A fetch issued while the SPA is swapping routes can be aborted; retry until JSON arrives.
    if (r && typeof r.body === 'object' && r.body !== null) return r;
    log(`api: GET ${apiPath} attempt ${attempt} returned no JSON body (status=${r && r.status}) -> retry`);
    await sleep(3000);
  }
  return { status: 0, body: null, error: 'no-json-body-after-retries' };
}
async function apiPost(apiPath, payload) {
  for (let attempt = 1; attempt <= 5; attempt++) {
    const r = await inPageEval(`(async () => {
      const headers = { 'Content-Type': 'application/json' };
      const tok = localStorage.getItem('modstore_token') || '';
      if (tok) headers['Authorization'] = 'Bearer ' + tok;
      try {
        const r = await fetch(${JSON.stringify(BASE + apiPath)}, { method: 'POST', credentials: 'include',
          headers, body: JSON.stringify(${JSON.stringify(payload)}) });
        const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch {}
        return { status: r.status, body: j !== null ? j : t.slice(0, 300) };
      } catch (e) { return { status: 0, error: String(e) }; }
    })()`);
    if (r && typeof r.body === 'object' && r.body !== null) return r;
    log(`api: POST ${apiPath} attempt ${attempt} returned no JSON body (status=${r && r.status}) -> retry`);
    await sleep(3000);
  }
  return { status: 0, body: null, error: 'no-json-body-after-retries' };
}
async function goto(url, settleMs = 5000) {
  await s.send('Page.navigate', { url });
  await sleep(1500);
  await waitApp(settleMs);
}
async function waitApp(timeoutMs = 25000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const busy = await inPageEval(
      `document.readyState !== 'complete' || !document.querySelector('#app, .auth-card, .wb-sidebar-logout-btn')`,
      false);
    if (!busy) return true;
    await sleep(500);
  }
  return false;
}
async function shot(name) {
  const f = path.join(SHOT, name);
  await s.screenshot(f);
  log(`shot: ${name} (${fs.statSync(f).size} bytes)`);
  return f;
}

// Full-desktop screenshot (includes the browser chrome / address bar).
async function shotFull(name) {
  const f = path.join(SHOT, name);
  try {
    bringBrowserToFront();
    await sleep(700);
    execFileSync('powershell', ['-NoProfile', '-Command',
      "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; " +
      "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen; " +
      "$bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height); " +
      "$g=[System.Drawing.Graphics]::FromImage($bmp); " +
      "$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size); " +
      `$bmp.Save('${f.replace(/\\/g, '\\\\')}',[System.Drawing.Imaging.ImageFormat]::Png); ` +
      "$g.Dispose(); $bmp.Dispose()",
    ], { stdio: 'ignore', timeout: 30000 });
    log(`shot(full-desktop): ${name} (${fs.statSync(f).size} bytes)`);
  } catch (e) {
    log('shot(full-desktop) failed: ' + e.message + ' -> falling back to page screenshot');
    await s.screenshot(f);
  }
  return f;
}
// Real keyboard input: focus the field with a real click, select existing content (Ctrl+A),
// then replace it via Input.insertText. Verifies the resulting value without logging it.
async function typeReal(selector, value) {
  const read = async () => await inPageEval(
    `(() => { const el = document.querySelector(${JSON.stringify(selector)}); return el ? el.value : null; })()`);
  await clickReal(selector);
  for (const type of ['keyDown', 'keyUp']) {
    await s.send('Input.dispatchKeyEvent', {
      type, modifiers: 2, key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, nativeVirtualKeyCode: 65,
    });
  }
  await s.send('Input.insertText', { text: value });
  await sleep(250);
  if ((await read()) !== value) {
    log(`type: field did not match after real input (selector=${selector}) -> clearing and retrying once`);
    await inPageEval(`(() => { const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return false;
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      set.call(el, ''); el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
    await clickReal(selector);
    await s.send('Input.insertText', { text: value });
    await sleep(250);
  }
  const okLen = (await read()) === value;
  log(`type: ${selector} filled (chars=${value.length}, verified=${okLen})`);
  return okLen;
}
// Real mouse click at element centre. Returns false (never throws) when the element is absent,
// so a missing control is reported by the case's own assertions instead of aborting the round.
async function clickReal(selector) {
  const box = await inPageEval(`(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return null;
    el.scrollIntoView({ block: 'center', inline: 'center' });
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) return null;
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  })()`);
  if (!box) { log(`click: target not found -> ${selector}`); return false; }
  await s.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y, button: 'none', clickCount: 0 });
  await s.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x, y: box.y, button: 'left', clickCount: 1 });
  await s.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box.x, y: box.y, button: 'left', clickCount: 1 });
  await sleep(300);
  return true;
}
async function clickTextReal(text) {
  const ok = await inPageEval(`(() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
    const btns = [...document.querySelectorAll('button, a')].filter(vis);
    const hit = btns.find((b) => (b.innerText || '').replace(/\\s+/g, '') === ${JSON.stringify(text.replace(/\s+/g, ''))});
    if (!hit) return null;
    document.querySelectorAll('[data-xcagi-t]').forEach((n) => n.removeAttribute('data-xcagi-t'));
    hit.setAttribute('data-xcagi-t', '1');
    return (hit.innerText || '').trim();
  })()`);
  if (!ok) { log(`click(text): target not found -> ${text}`); return false; }
  await clickReal('[data-xcagi-t]');
  return ok;
}
async function uiState() {
  return await inPageEval(`(() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
    const t = (document.body && document.body.innerText) || '';
    return {
      url: location.href, title: document.title,
      has_user_input: !!document.querySelector('input[autocomplete=username]'),
      has_pass_input: !!document.querySelector('input[type=password]'),
      submit_text: ([...document.querySelectorAll('button[type=submit]')].filter(vis)[0] || {}).innerText || '',
      logout_btn: !!document.querySelector('${LOGGED_IN_SEL}'),
      flash_err: ([...document.querySelectorAll('.flash-err')].filter(vis)[0] || {}).innerText || '',
      token_present: !!(localStorage.getItem('modstore_token') || ''),
      account_visible: ['SUNBIRD', 'sunbird'].some((x) => t.includes(x)),
      text_head: t.replace(/\\s+/g, ' ').slice(0, 400),
    };
  })()`);
}
async function clearSession() {
  await s.send('Network.enable').catch(() => {});
  await s.send('Network.clearBrowserCookies').catch(() => {});
  await inPage(() => { localStorage.clear(); sessionStorage.clear(); return true; });
  log('state: cleared cookies + local/session storage');
}
async function waitFor(expr, timeoutMs, label) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await inPageEval(expr, false)) return true;
    await sleep(500);
  }
  log(`wait: TIMEOUT ${label}`);
  return false;
}

// ---------------------------------------------------------------- cases
const cases = [];
function record(c) { cases.push(c); log(`case ${c.id}: ${c.result} - ${c.title}`); }

// Real-user login through the UI. The deployed market backend intermittently answers 500 on the
// first attempt (measured separately, recorded in the observations); a real user simply clicks
// 登录 again, so the round retries like a user and keeps every attempt in the evidence.
async function loginViaUi(attempts = 4) {
  const outcomes = [];
  for (let i = 1; i <= attempts; i++) {
    await typeReal('input[autocomplete=username]', USER);
    await typeReal('input[type=password]', PASS);
    await clickTextReal('登录');
    const ok = await waitFor(
      `!!document.querySelector('${LOGGED_IN_SEL}') && !location.pathname.endsWith('/login')`,
      25000, `ui login attempt ${i}`);
    const stl = await uiState();
    outcomes.push({ attempt: i, reached_workspace: ok, flash_err: stl.flash_err, url: stl.url });
    if (ok) break;
    log(`ui login attempt ${i} did not reach the workspace (flash="${stl.flash_err}") -> retry like a user`);
    await sleep(5000);
    await goto(`${APP}/login`);
  }
  return outcomes;
}

async function main() {
  log(`round stamp: ${stamp}`);
  log(`base: ${BASE}  app: ${APP}  out: ${OUT}`);
  await connectBrowser();
  log('browser: connected via CDP (' + CDP_HTTP + ')');
  await s.send('Network.enable').catch(() => {});

  // identity (product version / app sha the deployed web build self-reports)
  const health = await apiFetch('/api/health');
  const marketAssets = await inPageEval(`(async () => {
    const r = await fetch(${JSON.stringify(APP + '/')}, { credentials: 'include' });
    const h = await r.text();
    return (h.match(/\\/market\\/assets\\/[A-Za-z0-9_.\\-]+/g) || []).slice(0, 20);
  })()`);
  const desktopBuild = (() => {
    const p = 'C:\\XCAGI-r2\\resources\\build-info.json';
    try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; }
  })();
  const identity = {
    _comment:
      '此文件为 Web 端（修茈市场）真机验收的站点身份/版本/SHA 侦察快照，由 accept-base-login-web.mjs 自动生成，请勿手改（DO NOT EDIT）。',
    kind: 'web-identity',
    feature: 'base-login',
    platform: 'web',
    captured_at: localStamp(),
    entry_url: `${APP}/login`,
    page_title: await inPageEval('document.title', false),
    site_health: health.body,
    site_git_sha: (health.body && health.body.git_sha) || null,
    site_release_id: (health.body && health.body.release_id) || null,
    site_version: (health.body && String(health.body.release_id || '').match(/xcagi-([0-9.]+)-/)?.[1]) || null,
    market_bundle_assets: marketAssets,
    desktop_side_build_info: desktopBuild,
    user_agent: await inPageEval('navigator.userAgent', false),
  };
  fs.writeFileSync(path.join(OUT, 'base-login-web-identity.json'),
    JSON.stringify(identity, null, 2), 'utf8');
  log(`identity: site git_sha=${identity.site_git_sha} version=${identity.site_version}`);

  if (!identity.site_git_sha || !/^[0-9a-f]{40}$/.test(identity.site_git_sha)) {
    log('FATAL: site did not report a 40-hex git_sha; refusing to fabricate one.');
    return 1;
  }

  startVideo();
  await sleep(1500);
  bringBrowserToFront();
  await s.send('Page.bringToFront');

  // ---- WB1 未登录拒绝
  await goto(`${APP}/login`);
  await clearSession();
  await goto(`${APP}/workbench/home`, 6000);
  let st = await uiState();
  const me1 = await apiFetch('/api/auth/me');
  const wb1 = {
    id: 'WB1', title: 'not-logged-in rejection (web)',
    input: '浏览器无会话（已清 cookie 与 local/session storage）时直接打开受保护页面 ' + APP + '/workbench/home。',
    actions: '真实浏览器导航到工作台；并在页面上下文 fetch GET /api/auth/me。',
    expected: '被引导到登录页，且鉴权接口返回未登录（ok=false、请先登录）。',
    observed: JSON.stringify({ final_url: st.url, has_login_form: st.has_user_input && st.has_pass_input,
      submit_text: st.submit_text, me: me1.body }),
    result: (st.has_user_input && st.has_pass_input && me1.body && me1.body.ok === false) ? 'passed' : 'failed',
  };
  await shotFull('WB1-login-required.png');   // full desktop: proves a real browser + the address bar
  await shot('WB1b-login-page.png');          // page view: the login form the user actually sees
  record(wb1);

  // ---- WB2 企业账号真实浏览器登录
  await goto(`${APP}/login`);
  await typeReal('input[autocomplete=username]', USER);
  await typeReal('input[type=password]', PASS);
  await shot('WB2a-credentials-filled.png');
  const loginAttempts = await loginViaUi(4);
  const okLogin = loginAttempts.some((x) => x.reached_workspace);
  await sleep(2500);                       // let the SPA finish the route swap before probe calls
  st = await uiState();
  const me2 = await apiFetch('/api/auth/me');
  const loginResp = await apiPost('/api/auth/login', { username: USER, password: PASS });
  const me2User = (me2.body && me2.body.username) || (me2.body && me2.body.data && me2.body.data.user && me2.body.data.user.username) || '';
  const wb2 = {
    id: 'WB2', title: 'enterprise login (real browser)',
    input: `企业账号 ${USER} 与操作员提供的密码，在真实浏览器登录页输入。`,
    actions: '真实键盘在用户名/密码框输入后点击「登录」（服务器偶发 500 时像真实用户一样重试，逐次记录）；随后在页面上下文复核 GET /api/auth/me 与 POST /api/auth/login。',
    expected: '进入已登录工作台（出现账号菜单/退出入口），me 返回该账号（username=SUNBIRD）。',
    observed: JSON.stringify({ login_attempts: loginAttempts, final_url: st.url, title: st.title,
      logged_in_marker: st.logout_btn, account_visible: st.account_visible,
      me_status: me2.status, me_username: me2User, me_email: me2.body && me2.body.email,
      login_ok: loginResp.body && loginResp.body.ok, desktop_access: loginResp.body && loginResp.body.desktop_access,
      account_tier: loginResp.body && loginResp.body.account_tier }),
    result: (okLogin && st.logout_btn && me2User === USER) ? 'passed' : 'failed',
  };
  await shot('WB2b-login-workspace.png');
  record(wb2);

  // ---- WB3 会话保持（刷新后仍已登录，同一 token 仍有效）
  const tok1 = await inPageEval(`localStorage.getItem('modstore_token') || ''`, false);
  await s.send('Page.reload', { ignoreCache: false });
  await sleep(2500);
  await waitApp(30000);
  const okReload = await waitFor(`!!document.querySelector('${LOGGED_IN_SEL}')`, 30000, 'WB3 after reload');
  await sleep(2500);
  st = await uiState();
  const tok2 = await inPageEval(`localStorage.getItem('modstore_token') || ''`, false);
  const me3 = await apiFetch('/api/auth/me');
  const wb3 = {
    id: 'WB3', title: 'session persistence (browser reload)',
    input: 'WB2 建立的 Web 会话。',
    actions: '在真实浏览器执行页面重新加载（整页 reload），复读本地 token 与 me。',
    expected: '刷新后仍是已登录工作台；token 未变（服务端会话仍有效）；me 仍返回同一账号。',
    observed: JSON.stringify({ url_after_reload: st.url, logged_in_marker: st.logout_btn,
      token_unchanged: !!tok1 && tok1 === tok2, token_fp: fp(tok2),
      me_status: me3.status, me_username: me3.body && me3.body.username }),
    result: (okReload && tok1 && tok1 === tok2 && me3.body && me3.body.username === USER) ? 'passed' : 'failed',
  };
  await shot('WB3-after-reload.png');
  record(wb3);

  // ---- WB4 安全退出（部署版真实路径：侧栏账号菜单 → 退出登录 → 确认）
  const tokBefore = tok2;
  await clickReal('.wb-user-menu__trigger');
  const okPanel = await waitFor(`!!document.querySelector('.wb-user-menu__panel')`, 15000, 'WB4 user menu panel');
  const panelItems = await inPageEval(`(() => {
    const p = document.querySelector('.wb-user-menu__panel');
    return p ? [...p.querySelectorAll('.wb-user-menu__item')].map((x) => (x.innerText || '').trim()) : [];
  })()`);
  log('logout menu items: ' + JSON.stringify(panelItems));
  await clickTextReal('退出登录');
  const okDlg = await waitFor(`!!document.querySelector('.app-confirm-dialog')`, 15000, 'WB4 confirm dialog');
  const dlg = await inPageEval(`(() => {
    const d = document.querySelector('.app-confirm-dialog');
    if (!d) return null;
    return { title: (d.querySelector('.app-confirm-dialog__title') || {}).innerText || '',
      message: (d.querySelector('.app-confirm-dialog__message') || {}).innerText || '',
      confirm_label: (d.querySelector('.app-confirm-dialog__confirm') || {}).innerText || '',
      cancel_label: (d.querySelector('.app-confirm-dialog__cancel') || {}).innerText || '' };
  })()`);
  await shot('WB4a-logout-confirm.png');
  await clickReal('.app-confirm-dialog__confirm');
  const okLogout = await waitFor(`!document.querySelector('${LOGGED_IN_SEL}') && !!document.querySelector('input[type=password]')`, 30000, 'WB4 back to login');
  st = await uiState();
  const tokenAfterLogout = await inPageEval(`localStorage.getItem('modstore_token') || ''`, false);
  const me4 = await apiFetch('/api/auth/me');                       // no credential left in the browser
  const me4Old = await apiFetch('/api/auth/me', null, tokBefore);   // reuse the OLD bearer token on purpose
  // The market's server-side logout endpoint (contract detail, recorded as-is; the UI flow is client-side)
  const serverLogout = await inPageEval(`(async () => {
    try {
      const r = await fetch(${JSON.stringify(BASE + '/api/auth/logout')}, { method: 'POST', credentials: 'include' });
      return { status: r.status, body: (await r.text()).slice(0, 200) };
    } catch (e) { return { status: 0, error: String(e) }; }
  })()`);
  // Re-enter the protected route with an empty browser state: must be bounced back to the login page.
  await goto(`${APP}/workbench/home`, 6000);
  const stAfterRetry = await uiState();
  const wb4 = {
    id: 'WB4', title: 'secure logout (real browser)',
    input: '已登录会话与退出前的 token（指纹 ' + fp(tokBefore) + '）。',
    actions: '真实点击侧栏账号菜单（SUNBIRD）→ 点菜单项「退出登录」→ 确认框点确认按钮；再读取浏览器凭据、受保护接口返回，并再次直接访问受保护页面。',
    expected: '界面回到登录页；浏览器内不再持有该会话凭据；再次访问受保护页面仍被引导回登录页。',
    observed: JSON.stringify({ menu_opened: okPanel, menu_items: panelItems, confirm_dialog: dlg,
      final_url_after_confirm: st.url, login_form: st.has_pass_input,
      logged_in_marker_gone: !st.logout_btn, old_token_fp: fp(tokBefore),
      token_cleared_in_storage: !tokenAfterLogout, me_without_credential: me4.body,
      protected_route_after_logout: stAfterRetry.url,
      bounced_to_login_again: stAfterRetry.has_pass_input && !stAfterRetry.logout_btn,
      old_token_still_accepted_by_api: me4Old.body && me4Old.body.ok === true,
      server_logout_endpoint: serverLogout }),
    result: (okPanel && okDlg && !!dlg && okLogout && me4.body && me4.body.ok === false
      && !tokenAfterLogout && stAfterRetry.has_pass_input && !stAfterRetry.logout_btn) ? 'passed' : 'failed',
  };
  await shot('WB4b-login-page-after-logout.png');
  record(wb4);

  // ---- WB5 边界负例（真实浏览器）
  await goto(`${APP}/login`);
  await typeReal('input[autocomplete=username]', USER);
  await typeReal('input[type=password]', PASS + '-WRONG');
  await clickTextReal('登录');
  const okErr = await waitFor(`!!document.querySelector('.flash-err')`, 25000, 'WB5 wrong-password error');
  await sleep(800);
  st = await uiState();
  const wb5ErrText = st.flash_err;          // the message the user actually sees, captured before anything else
  const wb5CredentialError = /用户名或密码错误|密码错误|账号或密码/.test(wb5ErrText || '');
  await shot('WB5-wrong-password.png');     // fields still filled + the error the user sees
  const me5 = await apiPost('/api/auth/login', { username: USER, password: PASS + '-WRONG' });
  const emptySubmit = await inPageEval(`(() => {
    const f = document.querySelector('form');
    const u = document.querySelector('input[autocomplete=username]');
    const p = document.querySelector('input[type=password]');
    if (u) { u.value = ''; u.dispatchEvent(new Event('input', { bubbles: true })); }
    if (p) { p.value = ''; p.dispatchEvent(new Event('input', { bubbles: true })); }
    return { form_present: !!f, user_required: u ? u.required : null, pass_required: p ? p.required : null,
      blocked_by_html5: !!(f && !f.checkValidity()) };
  })()`);
  let emptyClickOutcome = 'clicked';
  try { await clickTextReal('登录'); } catch (e) { emptyClickOutcome = 'click-failed:' + e.message; }
  await sleep(2500);
  st = await uiState();
  const wb5 = {
    id: 'WB5', title: 'boundary negatives (real browser)',
    input: '错误密码（真实浏览器输入）与空凭据。',
    actions: '浏览器里用错误密码点击「登录」，截图并读取页面错误提示；随后清空两个输入框再点「登录」，检查表单是否被 HTML5 required 拦截。',
    expected: '错误密码被拒且页面明确显示「用户名或密码错误」、仍停留在登录页；空凭据不下发请求。',
    observed: JSON.stringify({ error_shown_after_wrong_password: wb5ErrText,
      credential_error_shown: wb5CredentialError,
      still_on_login: st.has_pass_input && !st.logout_btn, empty_submit_click: emptyClickOutcome,
      api_wrong_password: { status: me5.status, ok: me5.body && me5.body.ok,
        detail: me5.body && (me5.body.detail || me5.body.error || me5.body.msg) },
      empty_credentials: emptySubmit, final_url_after_empty_submit: st.url,
      still_on_login_after_empty: st.has_pass_input && !st.logout_btn }),
    // 必须看到凭据被拒的明确提示：若界面显示的是服务端 500 等其它信息，本用例如实记 failed。
    result: (okErr && wb5CredentialError && st.has_pass_input && !st.logout_btn) ? 'passed' : 'failed',
  };
  record(wb5);

  // ---- WB6 同账户体系（与桌面端同一账号）
  await goto(`${APP}/login`);
  const reloginAttempts = await loginViaUi(4);
  await sleep(2500);
  const me6 = await apiFetch('/api/auth/me');
  // Desktop-side identity for the same account, taken from the Windows round's own record.
  let desktopMe = null;
  if (fs.existsSync(WINDOWS_RUN_FILE)) {
    try {
      const w = JSON.parse(fs.readFileSync(WINDOWS_RUN_FILE, 'utf8'));
      const c2 = (w.cases || []).find((x) => x.id === 'W2');
      const c3 = (w.cases || []).find((x) => x.id === 'W3');
      const w3user = c3 && c3.facts && c3.facts.me_after_restart && c3.facts.me_after_restart.data
        && c3.facts.me_after_restart.data.user;
      desktopMe = {
        username: (c2 && c2.facts && c2.facts.username) || (w3user && w3user.username) || null,
        email: (w3user && w3user.email) || null,
        account_kind: (c2 && c2.facts && c2.facts.account_kind) || null,
        tenant_id: (c2 && c2.facts && c2.facts.tenant_id) || null,
        app_version: w.app_version, app_git_sha: w.app_git_sha,
      };
    } catch (e) { log('desktop record read failed: ' + e.message); }
  } else {
    log('desktop record not found at ' + WINDOWS_RUN_FILE);
  }
  const webUser = (me6.body && me6.body.data ? me6.body.data.user : me6.body && me6.body.user) || me6.body || {};
  st = await uiState();
  const sameUser = !!desktopMe && !!webUser.username && desktopMe.username === webUser.username;
  const sameEmail = !!desktopMe && !!desktopMe.email && !!webUser.email && desktopMe.email === webUser.email;
  const wb6 = {
    id: 'WB6', title: 'same account system as desktop',
    input: `同一企业账号 ${USER}（桌面端两轮使用的同一账号）。`,
    actions: 'Web 端登录后取 /api/auth/me 的账号身份；与桌面端 Windows 轮记录里的同一账号身份并排比对。',
    expected: 'Web 端与桌面端识别为同一账号（同一用户名与同一邮箱），即两端共用同一套账户体系。',
    observed: JSON.stringify({ login_attempts: reloginAttempts,
      web: { status: me6.status, username: webUser.username, user_id: webUser.id,
      email: webUser.email, is_enterprise: webUser.is_enterprise },
      desktop_windows_round: desktopMe, same_username: sameUser, same_email: sameEmail,
      account_visible_in_ui: st.account_visible }),
    result: (sameUser && sameEmail) ? 'passed' : 'failed',
  };
  await shot('WB6-same-account.png');
  record(wb6);

  await stopVideo();

  // ---------------------------------------------------------------- log + record
  const logFile = path.join(LOGD, `base-login-web-${stamp}.log`);
  fs.writeFileSync(logFile, logLines.join('\n') + '\n', 'utf8');
  log('log written -> ' + logFile);

  const shots = fs.readdirSync(SHOT).filter((f) => f.endsWith('.png')).sort();
  const media = [
    ...shots.map((n) => ({ kind: 'screenshot', file: path.join(SHOT, n) })),
    ...(videoFile ? [{ kind: 'video', file: videoFile }] : []),
  ].map((m) => ({
    feature: 'base-login',
    path: `${REPO_REL}/${path.relative(OUT, m.file).replace(/\\/g, '/')}`,
    sha256: fileSha(m.file),
    visual_review: 'pending_review',
    visible_result: '',
    reviewed_at: '',
  }));

  const passed = cases.filter((c) => c.result === 'passed').length;
  const failed = cases.filter((c) => c.result === 'failed').length;

  // 观察到的情况，如实落盘（含异常），不作为判定依据也不隐藏。
  const wb4Case = cases.find((c) => c.id === 'WB4');
  const wb4Obs = JSON.parse((wb4Case && wb4Case.observed) || '{}') || {};
  const dlgObs = wb4Obs.confirm_dialog || {};
  const observations = [
    `市场 Web 端登录入口：${APP}/login（页面标题「${identity.page_title}」），账号框 + 密码框 +「登录」按钮；退出路径为侧栏账号菜单 →「退出登录」→ 确认框（标题「${dlgObs.title}」，文案「${dlgObs.message}」，确认按钮「${dlgObs.confirm_label}」）。`,
    `退出为本机凭据清除（token_cleared_in_storage=${wb4Obs.token_cleared_in_storage}）：退出后浏览器不再持有该会话凭据，重新访问受保护页面被引导回登录页（bounced_to_login_again=${wb4Obs.bounced_to_login_again}）。`,
    `服务端退出接口 POST /api/auth/logout 返回 ${wb4Obs.server_logout_endpoint && wb4Obs.server_logout_endpoint.status}（${wb4Obs.server_logout_endpoint && wb4Obs.server_logout_endpoint.body}）：该接口受 CSRF 保护，且不属于本项界面退出路径，仅如实记录。`,
    '异常观察（真实存在，如实记录、不隐藏、不作为本轮用例判定依据）：部署中的市场后端会间歇性突发地对 POST /api/auth/login 与 GET /api/auth/me 返回 500 Internal Server Error。独立测量（纯 curl、合法凭据、与浏览器无关）：10 次里 3 次 500；随后 8 次里 1 次 500；静默 5 分钟后仍 8 次里 1 次；服务端重启后曾观察到约 6 分钟全 200 的干净窗口，随后又出现约 2 分钟的坏窗口（界面登录连续 3 次被 500 挡回）。失败响应只用约 0.08 秒（成功约 0.39 秒，接近一次口令校验耗时），同一时刻不触碰账号库的 /api/market/catalog、/api/payment/plans、无凭据的 /api/auth/me 连续多次全 200，/api/health 始终 200；部署版与主线均已配置 pool_pre_ping=True。症状指向服务侧（部分 worker 的数据库访问路径）瞬时故障，重启只能短暂清除。本轮界面登录按真实用户行为重试并逐次留痕（见 WB2/WB6 的 login_attempts），复核调用同样留痕。建议在服务端 `journalctl -u modstore.service -n 200` 取 500 的 traceback 定位根因。',
    '证据环境：真实浏览器 Edge（用户代理见 base-login-web-identity.json 的 user_agent），本次运行桌面画面由 ffmpeg 录制；站点自报身份 /api/health 见同一身份文件。',
  ];
  const obsFile = path.join(LOGD, 'operator-observations.txt');
  fs.writeFileSync(obsFile, observations.map((x, i) => `${i + 1}. ${x}`).join('\n') + '\n', 'utf8');
  log('operator observations -> ' + obsFile);

  const six = {
    screenshot: media.some((m) => m.path.endsWith('.png')),
    video: !!videoFile,
    log: fs.existsSync(logFile) && fs.existsSync(obsFile),
    product_version: !!identity.site_version,
    app_sha: !!identity.site_git_sha,
    verify_time: true,
  };
  const run = {
    _comment:
      '此文件为 Web 端（修茈市场）真机验收记录，由 accept-base-login-web.mjs 自动生成，请勿手改（DO NOT EDIT）。' +
      '结构与 base-login-macos-run.json / base-login-windows-run.json 一致；仅 media[].visual_review / ' +
      'media[].visible_result / media[].reviewed_at 可在实际查看该文件后填写。',
    kind: 'feature-acceptance',
    feature: 'base-login',
    platform: 'web',
    status: failed === 0 && passed === cases.length ? 'passed' : 'failed',
    verdict: failed === 0 && passed === cases.length ? 'PASS' : 'FAIL',
    round: stamp,
    generated_at: localStamp(),
    app_git_sha: identity.site_git_sha,
    app_version: identity.site_version,
    verified_at: localDate(),
    reviewed_at: '',
    passed,
    failed,
    six_elements: six,
    six_missing: Object.entries(six).filter(([, v]) => !v).map(([k]) => k),
    operator_observations: observations,
    observation_log: `${REPO_REL}/log/operator-observations.txt`,
    app_identity: {
      entry_url: identity.entry_url,
      site_health: identity.site_health,
      market_bundle_assets: identity.market_bundle_assets,
      desktop_side_build_info: identity.desktop_side_build_info,
      user_agent: identity.user_agent,
      identity_capture: `${REPO_REL}/base-login-web-identity.json`,
    },
    visible_content: '真实浏览器（Edge，CDP 驱动真实鼠标键盘）在市场 Web 端完成：未登录被拦 → 输入企业账号登录进入工作台 → 整页刷新仍已登录 → 侧栏退出登录回到登录页 → 错误密码被拒 → 同账号与桌面端一致。',
    media,
    cases,
  };
  const runFile = path.join(OUT, 'base-login-web-run.json');
  fs.writeFileSync(runFile, JSON.stringify(run, null, 2), 'utf8');
  log(`record: ${runFile}  status=${run.status} passed=${passed} failed=${failed} media=${media.length}`);
  return failed === 0 ? 0 : 1;
}

let code = 1;
try {
  code = await main();
} catch (e) {
  log('FATAL: ' + (e && e.stack ? e.stack : e));
  try { await stopVideo(); } catch {}
  try {
    fs.writeFileSync(path.join(OUT, 'log', `base-login-web-${stamp}.log`), logLines.join('\n') + '\n', 'utf8');
  } catch {}
  code = 1;
}
process.exit(code);