// ui-sampler.mjs - continuous UI-side sampler for the base-login Windows round (read-only).
//
// Appends one JSONL row every few seconds: what the renderer shows (URL, window title, sidebar
// status text + tone, login form / workspace) and the /api/health payload as seen from inside the
// page. This is the raw trace behind W7: it shows the cold-start warm-up window right after a
// restart and the moment the UI converges, including the 30s health poll the sidebar uses.
//
//   node ui-sampler.mjs            (env: CDP_HTTP, OUT_FILE, SECONDS)
import fs from 'node:fs';
import path from 'node:path';
import { Session } from './cdp.mjs';

const OUT = process.env.OUT_FILE || 'ui-timeline.jsonl';
const SECONDS = Number(process.env.SECONDS || 1200);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

fs.mkdirSync(path.dirname(OUT), { recursive: true });

async function connectWithRetry(deadline) {
  while (Date.now() < deadline) {
    try { return await Session.connect(); } catch { await sleep(1500); }
  }
  return null;
}

const end = Date.now() + SECONDS * 1000;
let s = await connectWithRetry(Math.min(end, Date.now() + 120_000));
if (!s) { console.log('NO-CDP'); process.exit(3); }
console.log('cdp connected');

const probe = `(async () => {
  const statusEl = document.querySelector('[role=status]');
  const dot = document.querySelector('.status-dot');
  let health = null;
  try {
    const r = await fetch('/api/health', { credentials: 'include', cache: 'no-store' });
    const d = await r.json();
    health = { http: r.status, status: d.status, runtime_status: d.runtime && d.runtime.status,
      degradedReasons: d.degradedReasons || [], blockers: ((d.runtime && d.runtime.blockers) || []).map(b => b.component) };
  } catch (e) { health = { error: String(e) }; }
  return {
    url: location.href,
    title: document.title,
    uiText: statusEl ? (statusEl.textContent || '').trim() : null,
    tone: dot ? [...dot.classList].join(' ') : null,
    loginForm: !!document.querySelector('input[name=username]'),
    sidebarItems: document.querySelectorAll('button.menu-item').length,
    health,
  };
})()`;

let n = 0;
const rows = [];
// NOTE: appendFileSync on this machine's network share fails with EBADF, so the sampler keeps the
// rows in memory and rewrites the file each tick (the file stays small: one row per few seconds).
while (Date.now() < end) {
  n++;
  const t = new Date().toTimeString().slice(0, 8);
  let row;
  try {
    row = { t, ...(await s.eval(probe)) };
  } catch (e) {
    row = { t, error: String(e).slice(0, 200) };
    try { s.close(); } catch {}
    s = await connectWithRetry(Math.min(end, Date.now() + 120_000));
    if (!s) { rows.push({ t, error: 'cdp lost' }); fs.writeFileSync(OUT, rows.map((r) => JSON.stringify(r)).join('\n') + '\n'); break; }
  }
  rows.push(row);
  fs.writeFileSync(OUT, rows.map((r) => JSON.stringify(r)).join('\n') + '\n');
  await sleep(3000);
}
try { s.close(); } catch {}
console.log('samples=' + n);