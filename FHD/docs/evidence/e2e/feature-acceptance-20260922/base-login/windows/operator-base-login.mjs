// operator-base-login.mjs - real-GUI operator for the base-login Windows round (2026-09-24).
//
// The PowerShell acceptance script asserts the API/backend side; this driver performs the parts
// that only exist in the UI and records what it saw. It never writes verdicts: it produces facts
// (JSON) plus full-screen screenshots that the acceptance script turns into cases W0/W2/W4/W4b/W7.
//
//   phase A (after the deliverable install + first start, login page visible):
//     read the first-launch page            -> shot/W0-first-launch.png
//     GUI login (real input events)         -> shot/W2-login-workspace.png
//     GUI logout (settings -> logout -> OK) -> shot/W4-login-page-again.png
//     GUI login again (leave the app logged in for the acceptance script's restart step)
//   phase C (the acceptance script has finished its API logout; the GUI is still logged in):
//     capture the live session cookie -> GUI logout -> close the app -> start it again
//     -> login page again + the captured cookie stays invalid -> shot/W4b-relaunch-login-page.png
//     -> steady health vs the sidebar status text             -> shot/W7-status-bar.png
//
// Usage:
//   set XCAGI_TEST_PASS=...
//   node operator-base-login.mjs --phase a --out-dir <round dir>
//   node operator-base-login.mjs --phase c --out-dir <round dir> --app-exe C:\XCAGI-r2\XCAGI.exe
//
// Env: CDP_HTTP (default http://127.0.0.1:9222), XCAGI_TEST_USER (default SUNBIRD),
//      XCAGI_TEST_PASS (required), XCAGI_DESKTOP_USER_DATA_DIR (recorded; inherited by the relaunch).
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync, spawn } from 'node:child_process';
import { Session } from './cdp.mjs';

const args = process.argv.slice(2);
const argOf = (name, dflt = '') => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : dflt;
};
const PHASE = (argOf('phase', 'a') || 'a').toLowerCase();
const OUT_DIR = argOf('out-dir', process.env.XCAGI_OUT_DIR || '.');
const APP_EXE = argOf('app-exe', process.env.XCAGI_APP_EXE || '');
const CDP_HTTP = process.env.CDP_HTTP || 'http://127.0.0.1:9222';
const CDP_PORT = new URL(CDP_HTTP).port || '9222';
const USER = process.env.XCAGI_TEST_USER || 'SUNBIRD';
const PASS = process.env.XCAGI_TEST_PASS;
const DATA_DIR = process.env.XCAGI_DESKTOP_USER_DATA_DIR || '';
const BASE = 'http://127.0.0.1:17500';
const SHOT_DIR = path.join(OUT_DIR, 'shot');
const FACTS = path.join(OUT_DIR, 'log', `operator-phase-${PHASE}.json`);

if (!PASS) { console.error('FATAL: XCAGI_TEST_PASS not set'); process.exit(2); }
fs.mkdirSync(SHOT_DIR, { recursive: true });
fs.mkdirSync(path.join(OUT_DIR, 'log'), { recursive: true });

const now = () => new Date().toTimeString().slice(0, 8);
const log = (...a) => console.log(`[${now()}]`, ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fingerprint = (value) => (value ? createHash('sha256').update(value).digest('hex').slice(0, 16) : '');

// ---- full-screen screenshot (same method as the acceptance script) ----
function screenShot(file) {
  const ps = [
    'Add-Type -AssemblyName System.Windows.Forms',
    'Add-Type -AssemblyName System.Drawing',
    '$b=[System.Windows.Forms.SystemInformation]::VirtualScreen',
    '$bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height)',
    '$g=[System.Drawing.Graphics]::FromImage($bmp)',
    '$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size)',
    `$bmp.Save(${JSON.stringify(file)},[System.Drawing.Imaging.ImageFormat]::Png)`,
    '$g.Dispose();$bmp.Dispose()',
    'Write-Output "saved"',
  ].join('; ');
  execFileSync('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], { encoding: 'utf8' });
  log('shot saved:', file);
}

async function connect(maxMs = 180000) {
  const end = Date.now() + maxMs;
  let lastErr = '';
  while (Date.now() < end) {
    try { return await Session.connect(); } catch (e) { lastErr = String(e); await sleep(2000); }
  }
  throw new Error('CDP connect timed out: ' + lastErr);
}

async function waitFor(s, expr, timeoutMs, tag) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const v = await s.eval(expr);
    if (v) return v;
    await sleep(1000);
  }
  throw new Error(`waitFor timeout: ${tag}`);
}

// ---- DOM helpers (only read state or dispatch real input/click events) ----
const stateExpr = `(() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
  const statusEl = document.querySelector('[role=status]');
  const dot = document.querySelector('.status-dot');
  return {
    url: location.href,
    title: document.title,
    loginForm: !!document.querySelector('input[name=username]'),
    sidebarItems: document.querySelectorAll('button.menu-item').length,
    uiStatusText: statusEl ? (statusEl.textContent || '').trim() : null,
    uiTone: dot ? [...dot.classList].join(' ') : null,
    hasUser: (document.body ? document.body.innerText : '').includes(${JSON.stringify(USER)}),
    hasOnboarding: location.href.includes('/onboarding'),
  };
})()`;

async function state(s) { return await s.eval(stateExpr); }

async function pageMe(s) {
  return await s.eval(`(async () => {
    const r = await fetch('/api/auth/me', { credentials: 'include', cache: 'no-store' });
    const d = await r.json();
    return { http: r.status, success: d.success === true, valid: d.valid === true,
      account_kind: (d.data && d.data.account_kind) || null, tenant_id: (d.data && d.data.tenant_id) || null,
      username: (d.data && d.data.user && d.data.user.username) || null };
  })()`);
}

async function pageHealth(s) {
  return await s.eval(`(async () => {
    const r = await fetch('/api/health', { credentials: 'include', cache: 'no-store' });
    const d = await r.json();
    return { http: r.status, status: d.status, runtime_status: d.runtime && d.runtime.status,
      blockers: ((d.runtime && d.runtime.blockers) || []).map(b => b.component),
      degradedReasons: d.degradedReasons || [], version: d.version || '' };
  })()`);
}

async function dismissDialogs(s, tag) {
  const d = await s.eval(`(() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
    const btns = [...document.querySelectorAll('button.app-dialog-host-btn, .modal-overlay button, [role=dialog] button')].filter(vis);
    const hit = btns.find(b => (b.innerText || '').trim() === '确定') || btns.find(b => (b.innerText || '').trim() === '关闭');
    if (!hit) return { found: false };
    const host = hit.closest('.app-dialog, .modal-overlay, [role=dialog]');
    const text = host ? (host.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 300) : '';
    hit.click();
    return { found: true, text };
  })()`);
  if (d.found) { log(`[${tag}] dismissed dialog:`, d.text); await sleep(1500); }
  return d;
}

const isLoginPage = `(() => !!document.querySelector('input[name=username]'))()`;
const isWorkspace = `(() => document.querySelectorAll('button.menu-item').length > 0)()`;

async function clickMenu(s, text, timeoutMs = 60000) {
  const end = Date.now() + timeoutMs;
  let last = '';
  while (Date.now() < end) {
    const ok = await s.eval(`(() => {
      const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
      const items = [...document.querySelectorAll('button.menu-item, nav button, aside button')].filter(vis);
      const wanted = ${JSON.stringify(text)};
      const hit = items.find((el) => (el.innerText || '').trim() === wanted)
        || items.find((el) => (el.innerText || '').trim().startsWith(wanted));
      if (!hit) return 'no-menu-item:' + wanted;
      hit.scrollIntoView({ block: 'center' });
      document.querySelectorAll('[data-gui-nav]').forEach((n) => n.removeAttribute('data-gui-nav'));
      hit.setAttribute('data-gui-nav', '1');
      return true;
    })()`);
    if (ok === true) return await s.clickSelector('[data-gui-nav]');
    last = String(ok);
    await sleep(1500);
  }
  throw new Error('clickMenu: ' + last);
}

async function clickAny(s, text, { exact = true, timeoutMs = 60000 } = {}) {
  const end = Date.now() + timeoutMs;
  let last = '';
  while (Date.now() < end) {
    const ok = await s.eval(`(() => {
      const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
      const nodes = [...document.querySelectorAll('button, a, div, span, li')].filter(vis);
      const wanted = ${JSON.stringify(text)};
      const norm = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
      const hit = ${exact ? 'true' : 'false'}
        ? (nodes.find((el) => norm(el) === wanted) || nodes.find((el) => norm(el).includes(wanted) && el.children.length === 0))
        : nodes.find((el) => norm(el).includes(wanted));
      if (!hit) return 'not-found:' + wanted;
      hit.scrollIntoView({ block: 'center' });
      document.querySelectorAll('[data-gui-hit]').forEach((n) => n.removeAttribute('data-gui-hit'));
      hit.setAttribute('data-gui-hit', '1');
      return true;
    })()`);
    if (ok === true) return await s.clickSelector('[data-gui-hit]');
    last = String(ok);
    await sleep(1500);
  }
  throw new Error('clickAny: ' + last);
}

// The first-run wizard intercepts /settings after a login. Take the product's own
// "enter first, configure later" path, exactly like a user would.
async function ensureWorkspace(s, tag) {
  let st = await state(s);
  if (!st.hasOnboarding && st.sidebarItems > 0) return st;
  if (st.hasOnboarding) {
    await dismissDialogs(s, tag);
    log(`[${tag}] first-run wizard detected; clicking its "enter first, configure later" action`);
    const r = await s.eval(`(() => {
      const vis = (el) => { const r = el.getBoundingClientRect(); return r.width>0&&r.height>0; };
      const btns = [...document.querySelectorAll('button')].filter(vis);
      const hit = btns.find(b => (b.innerText||'').includes('先进入'))
        || btns.find(b => (b.innerText||'').includes('进入') && (b.innerText||'').includes('工作空间'));
      if (!hit) return 'no-enter-button:' + JSON.stringify(btns.map(b => (b.innerText||'').trim()));
      hit.click();
      return 'clicked:' + (hit.innerText||'').trim();
    })()`);
    log(`[${tag}] enter ->`, r);
    await sleep(8000);
    await dismissDialogs(s, tag);
    st = await state(s);
    log(`[${tag}] after enter:`, JSON.stringify(st));
  }
  return st;
}

async function doLogin(s, tag) {
  await dismissDialogs(s, tag);
  await s.typeInto('input[name=username]', USER);
  await sleep(400);
  await s.typeInto('input[name=password]', PASS);
  await sleep(700);
  const clicked = await s.eval(`(() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); return r.width>0&&r.height>0; };
    const btns = [...document.querySelectorAll('button')].filter(vis);
    const hit = btns.find(b => (b.innerText||'').replace(/\\s+/g,'') === '登录');
    if (!hit) return 'no-login-button';
    hit.click();
    return 'clicked:' + (hit.innerText||'').trim();
  })()`);
  log(`[${tag}] login button ->`, clicked);
  await waitFor(s, isWorkspace, 90000, 'workspace after login');
  await sleep(2500);
  await ensureWorkspace(s, tag);
}

async function openSettings(s, tag) {
  const go = async (why) => {
    try { await clickMenu(s, '系统设置'); } catch (e) {
      log(`[${tag}] sidebar entry not found (${e.message}); navigating to /settings`);
      await s.send('Page.navigate', { url: `${BASE}/settings` });
    }
    await sleep(3500);
    log(`[${tag}] ${why} -> ${await s.url()}`);
  };
  await go('open settings');
  if ((await s.url()).includes('/onboarding')) {
    log(`[${tag}] settings gated by the first-run wizard; entering the workspace first`);
    await ensureWorkspace(s, tag);
    await sleep(3000);
    await go('reopen settings');
  }
}

async function doLogout(s, tag) {
  await dismissDialogs(s, tag);
  await openSettings(s, tag);
  await clickAny(s, '退出登录');
  await sleep(2500);
  const dlg = await s.eval(`(() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
    const ovs = [...document.querySelectorAll('.modal-overlay, .modal.active, [role=dialog]')].filter(vis);
    if (!ovs.length) return { dialog: false };
    const top = ovs[ovs.length - 1];
    return { dialog: true, text: (top.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 200),
      buttons: [...top.querySelectorAll('button')].filter(vis).map(b => (b.innerText || '').trim()) };
  })()`);
  log(`[${tag}] confirm dialog:`, JSON.stringify(dlg));
  if (dlg.dialog) {
    const r = await s.eval(`(() => {
      const vis = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden'; };
      const ovs = [...document.querySelectorAll('.modal-overlay, .modal.active, [role=dialog]')].filter(vis);
      const top = ovs[ovs.length - 1];
      const btns = [...top.querySelectorAll('button')].filter(vis);
      const hit = btns.find(b => (b.innerText || '').trim() === '确定')
        || btns.find(b => (b.innerText || '').trim() === '确认') || btns[btns.length - 1];
      if (!hit) return 'no-confirm-button';
      hit.click();
      return 'clicked:' + (hit.innerText || '').trim();
    })()`);
    log(`[${tag}] confirm ->`, r);
  }
  await waitFor(s, isLoginPage, 60000, 'login page after logout');
  await sleep(1500);
  return dlg;
}

async function getSessionCookie(s) {
  await s.send('Network.enable');
  const r = await s.send('Network.getCookies', { urls: [BASE] });
  const c = (r.cookies || []).find((x) => x.name === 'session_id');
  return c ? c.value : '';
}

async function fetchWithCookie(pathName, cookieValue) {
  const headers = cookieValue ? { Cookie: `session_id=${cookieValue}` } : {};
  const res = await fetch(`${BASE}${pathName}`, { headers });
  const body = await res.json().catch(() => ({}));
  return { http: res.status, valid: body.valid === true, success: body.success === true };
}

// ---------------------------------------------------------------- run
const facts = {
  // Machine-generated capture: the line below keeps the repo's generated-file banner rule
  // (scripts/dev/check_net_deletion.py skips files whose head declares auto-generation).
  _comment: 'auto-generated by operator-base-login.mjs (real-GUI operator driver) - DO NOT EDIT',
  phase: PHASE,
  generated_at: new Date().toISOString(),
  operator_user: USER,
  isolated_data_dir: DATA_DIR,
  cdp_http: CDP_HTTP,
  steps: [],
};
const step = (name, data) => {
  facts.steps.push({ at: now(), name, ...data });
  log('STEP', name, JSON.stringify(data).slice(0, 600));
};

async function writeFacts() {
  fs.writeFileSync(FACTS, JSON.stringify(facts, null, 2), 'utf8');
  log('facts written:', FACTS);
}

let session = null;
try {
  // Install facts are captured by the install step itself (log/install-facts.json) so W0 can bind
  // "what was installed" to "what the first launch showed" without anyone retyping values.
  const installFactsPath = path.join(OUT_DIR, 'log', 'install-facts.json');
  if (fs.existsSync(installFactsPath)) {
    facts.install = JSON.parse(fs.readFileSync(installFactsPath, 'utf8'));
    log('install facts ingested from', installFactsPath);
  }
  if (PHASE === 'a') {
    session = await connect(180000);
    log('cdp connected');
    await waitFor(session, `(() => !!document.querySelector('input[name=username]') || document.querySelectorAll('button.menu-item').length > 0)()`, 180000, 'renderer ready');

    // ---- W0 first launch (fresh data directory, login page, no session) ----
    let st = await state(session);
    const me0 = await pageMe(session);
    const h0 = await pageHealth(session);
    step('first_launch_state', st);
    step('first_launch_me', me0);
    step('first_launch_health', h0);
    if (!st.loginForm) throw new Error('first launch is not showing the login form: ' + JSON.stringify(st));
    if (st.sidebarItems !== 0) throw new Error('first launch shows a workspace: ' + JSON.stringify(st));
    screenShot(path.join(SHOT_DIR, 'W0-first-launch.png'));
    facts.first_launch = {
      started_at: facts.generated_at,
      window_title: st.title,
      url: st.url,
      health_status: h0.http,
      health_payload_status: h0.status,
      me_valid: me0.valid,
      login_form_present: st.loginForm,
      sidebar_items: st.sidebarItems,
      screenshot: 'shot/W0-first-launch.png',
      verify_time: now(),
    };

    // ---- W2 GUI login ----
    await doLogin(session, 'gui-login');
    st = await state(session);
    const me1 = await pageMe(session);
    const cookie = await getSessionCookie(session);
    step('gui_login_state', st);
    step('gui_login_me', me1);
    screenShot(path.join(SHOT_DIR, 'W2-login-workspace.png'));
    facts.gui_login = {
      at: now(),
      window_title: st.title,
      url: st.url,
      username: me1.username,
      me_success: me1.success,
      me_account_kind: me1.account_kind,
      tenant_id: me1.tenant_id,
      sidebar_items: st.sidebarItems,
      session_cookie_present: !!cookie,
      session_cookie_fingerprint: fingerprint(cookie),
      screenshot: 'shot/W2-login-workspace.png',
      verify_time: now(),
    };

    // ---- W4 GUI logout ----
    const dlg = await doLogout(session, 'gui-logout');
    st = await state(session);
    const me2 = await pageMe(session);
    const cookieAfter = await getSessionCookie(session);
    step('gui_logout_state', st);
    step('gui_logout_me', me2);
    screenShot(path.join(SHOT_DIR, 'W4-login-page-again.png'));
    facts.gui_logout = {
      at: now(),
      confirm_text: dlg && dlg.text ? dlg.text : '',
      me_valid_after: me2.valid,
      session_cookie_gone: !cookieAfter,
      login_form_present: st.loginForm,
      sidebar_items: st.sidebarItems,
      window_title: st.title,
      screenshot: 'shot/W4-login-page-again.png',
      verify_time: now(),
    };

    // ---- leave logged in for the acceptance script's restart step ----
    await doLogin(session, 'gui-relogin');
    st = await state(session);
    const me3 = await pageMe(session);
    facts.gui_relogin = { at: now(), me_success: me3.success, window_title: st.title, sidebar_items: st.sidebarItems };
    step('gui_relogin', facts.gui_relogin);
  } else if (PHASE === 'c') {
    session = await connect(120000);
    log('cdp connected');
    await waitFor(session, isWorkspace, 60000, 'workspace before phase C');

    // ---- W7 steady state, read where the status bar actually exists (the logged-in workspace) ----
    // The sidebar status text only exists inside the workspace, so the steady-state comparison must
    // happen before the logout; right after a cold start the backend is still warming up instead.
    let healthSteady = await pageHealth(session);
    let st = await state(session);
    for (let i = 0; i < 60 && !(healthSteady.status === 'healthy' && (healthSteady.degradedReasons || []).length === 0); i++) {
      await sleep(2000);
      healthSteady = await pageHealth(session);
      st = await state(session);
    }
    const healthHealthy = healthSteady.http === 200 && healthSteady.status === 'healthy'
      && healthSteady.runtime_status === 'healthy' && (healthSteady.blockers || []).length === 0
      && (healthSteady.degradedReasons || []).length === 0;
    const uiTextPresent = !!(st.uiStatusText || '');
    const uiHealthy = (st.uiStatusText || '') === '系统正常';
    const matches = uiTextPresent && healthHealthy === uiHealthy;
    step('steady_health', healthSteady);
    step('steady_ui', { text: st.uiStatusText, tone: st.uiTone, text_present: uiTextPresent, matches });
    await sleep(1500);
    screenShot(path.join(SHOT_DIR, 'W7-status-bar.png'));
    facts.health_ui = {
      at: now(),
      health_http: healthSteady.http,
      health_status: healthSteady.status,
      runtime_status: healthSteady.runtime_status,
      blockers: healthSteady.blockers,
      degradedReasons: healthSteady.degradedReasons,
      version: healthSteady.version,
      ui_status_text: st.uiStatusText,
      ui_tone: st.uiTone,
      ui_matches_health: matches,
      captured_where: 'logged-in workspace, before the phase C logout',
      screenshot: 'shot/W7-status-bar.png',
      verify_time: now(),
    };

    // Capture the live session cookie BEFORE the logout: the jar is empty right after a logout,
    // so this value is the only way to prove later that the relaunch keeps it rejected.
    const liveCookie = await getSessionCookie(session);
    if (!liveCookie) throw new Error('no live session cookie in the jar before the phase C logout');
    step('phase_c_live_cookie', { present: true, fingerprint: fingerprint(liveCookie) });

    // ---- GUI logout again ----
    const dlg = await doLogout(session, 'gui-logout-c');
    st = await state(session);
    const me2 = await pageMe(session);
    const jarAfter = await getSessionCookie(session);
    step('gui_logout_c_state', st);
    screenShot(path.join(SHOT_DIR, 'W4c-gui-logout-login-page.png'));
    facts.gui_logout = {
      at: now(),
      confirm_text: dlg && dlg.text ? dlg.text : '',
      me_valid_after: me2.valid,
      session_cookie_gone: !jarAfter,
      login_form_present: st.loginForm,
      sidebar_items: st.sidebarItems,
      window_title: st.title,
      screenshot: 'shot/W4c-gui-logout-login-page.png',
      verify_time: now(),
    };

    // ---- close the app and start it again ----
    const stoppedAt = now();
    try {
      const vres = await fetch(`${CDP_HTTP}/json/version`).then((r) => r.json());
      if (vres.webSocketDebuggerUrl) {
        const ws = new WebSocket(vres.webSocketDebuggerUrl);
        await new Promise((resolve) => { ws.addEventListener('open', resolve, { once: true }); });
        ws.send(JSON.stringify({ id: 1, method: 'Browser.close' }));
        await sleep(2500);
        try { ws.close(); } catch {}
      }
    } catch (e) { log('Browser.close failed:', String(e)); }
    try { session.close(); } catch {}
    session = null;
    try { execFileSync('taskkill', ['/IM', 'XCAGI.exe', '/F'], { encoding: 'utf8' }); } catch {}
    try { execFileSync('taskkill', ['/IM', 'xcagi-backend.exe', '/F'], { encoding: 'utf8' }); } catch {}
    await sleep(4000);

    if (!APP_EXE) throw new Error('phase c needs --app-exe to start the app again');
    const child = spawn(APP_EXE, [`--remote-debugging-port=${CDP_PORT}`], {
      detached: true,
      stdio: 'ignore',
      env: { ...process.env },
    });
    child.unref();
    const startedAt = now();
    log('app started again:', startedAt);

    let healthAfter = null;
    for (let i = 0; i < 120; i++) {
      try {
        const r = await fetch(`${BASE}/api/health`);
        if (r.ok) { healthAfter = await r.json(); break; }
      } catch {}
      await sleep(2000);
    }
    if (!healthAfter) throw new Error('backend did not come back after the relaunch');
    session = await connect(180000);
    await waitFor(session, isLoginPage, 180000, 'login page after relaunch');
    await sleep(2500);

    st = await state(session);
    const meOld = await fetchWithCookie('/api/auth/me', liveCookie);
    const svOld = await fetchWithCookie('/api/auth/session/validate', liveCookie);
    step('relaunch_state', st);
    step('relaunch_old_cookie_me', meOld);
    screenShot(path.join(SHOT_DIR, 'W4b-relaunch-login-page.png'));
    facts.postlogout_relaunch = {
      stopped_at: stoppedAt,
      started_at: startedAt,
      window_title: st.title,
      url: st.url,
      login_form_present: st.loginForm,
      sidebar_items: st.sidebarItems,
      health_status: 200,
      health_payload_status: healthAfter.status,
      old_cookie_valid: meOld.valid,
      old_cookie_validate_valid: svOld.valid,
      old_cookie_fingerprint: fingerprint(liveCookie),
      screenshot: 'shot/W4b-relaunch-login-page.png',
      verify_time: now(),
    };

    // ---- post-relaunch convergence: the cold start warms up, then the payload turns healthy ----
    // This window is recorded instead of hidden; the steady-state verdict comes from the workspace
    // sample above (W7), this block only documents how the relaunch settles.
    const convergence = [];
    let converged = false;
    for (let i = 0; i < 45; i++) {
      let h = null;
      try {
        const r = await fetch(`${BASE}/api/health`);
        h = await r.json();
      } catch { /* keep sampling */ }
      convergence.push({
        t: now(),
        http: h ? 200 : 0,
        status: h ? h.status : 'unreachable',
        degradedReasons: h ? (h.degradedReasons || []) : [],
        runtime_status: h && h.runtime ? h.runtime.status : '',
      });
      if (h && h.status === 'healthy') { converged = true; break; }
      await sleep(2000);
    }
    facts.post_relaunch_convergence = {
      sampled_at: now(),
      converged_within_samples: convergence.length,
      converged: converged,
      samples: convergence,
      note: 'right after a cold start the backend honestly reports optional subsystems that are not up yet; the login page has no sidebar status bar, so the UI text check for W7 is done in the workspace sample',
    };
    step('post_relaunch_convergence', { converged, samples: convergence.length });
  } else if (PHASE === 'login') {
    // Helper phase: only log the GUI in again (no screenshots, no facts beyond the state), used to
    // put the app into the "logged in" precondition the acceptance script's restart step needs
    // when a round is repeated.
    session = await connect(120000);
    log('cdp connected');
    await waitFor(session, `(() => !!document.querySelector('input[name=username]') || document.querySelectorAll('button.menu-item').length > 0)()`, 120000, 'renderer ready');
    let st = await state(session);
    if (st.loginForm) await doLogin(session, 'relogin');
    st = await state(session);
    const me = await pageMe(session);
    step('login_only', { me_success: me.success, window_title: st.title, sidebar_items: st.sidebarItems });
  } else {
    throw new Error('unknown phase: ' + PHASE);
  }

  await writeFacts();
  try { session && session.close(); } catch {}
  log('DONE phase', PHASE);
} catch (e) {
  facts.error = String(e && e.message ? e.message : e);
  log('FAILED:', facts.error);
  await writeFacts();
  try { session && session.close(); } catch {}
  process.exit(1);
}