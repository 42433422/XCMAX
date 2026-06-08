/**
 * 日更行动条目渲染（Agentic Business OS）—— 完全沿用断点清单页设计系统
 * - kind=patch  → 注入「断点清单」#s-gaps（顶部渐变计数盒 + .gap-grid/.gap-card 规范卡片）
 * - kind=update → 注入「实现目标/路线图」#s-roadmap（同设计系统）
 * 数据：FHD /api/xcmax/admin/action-items（本地 MODstore :8788 优先）。每日刷新。
 * 全 try/catch；找不到容器/接口失败则静默降级，不影响既有页面。
 */
(function (global) {
  'use strict';

  const PRIORITY_ORDER = ['P0', 'P1', 'P2', ''];
  const LINE_LABEL = { 'P-W': 'P-W 网站线', 'P-S': 'P-S 软件线', 'P-App': 'P-App 移动发布线', 'S-R': 'S-R 归档线' };
  const LINE_LOOP = { 'P-W': 'build', 'P-S': 'build', 'P-App': 'build', 'S-R': 'sell' };
  const STATUS_LABEL = { open: '待处理', dispatched: '已派发', in_progress: '进行中', merged: '已合并', closed: '已关闭' };
  const DONE = { merged: 1, closed: 1 };
  const rendered = { patch: false, update: false };

  function api(path) {
    try { return global.XCAGIApi ? global.XCAGIApi.url(path) : path; } catch (_e) { return path; }
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }
  async function fetchJson(path) {
    try {
      const r = await fetch(api(path), { headers: { Accept: 'application/json' }, credentials: 'include' });
      if (!r.ok) return null;
      const ct = (r.headers.get('content-type') || '').toLowerCase();
      if (ct.includes('text/html')) return null;
      return await r.json();
    } catch (_e) { return null; }
  }

  /* ── localhost 跨源兜底：FHD 代理拿不到时直连本地 MODstore :8788 ── */
  function isLocalHost() {
    try { return /^(localhost|127\.0\.0\.1|\[::1\])$/.test(global.location.hostname); } catch (_e) { return false; }
  }
  function modstoreBase() {
    return String(global.XCAGI_MODSTORE_URL || 'http://127.0.0.1:8788').replace(/\/$/, '');
  }
  let _mtokenPromise = null;
  function modstoreToken() {
    if (_mtokenPromise) return _mtokenPromise;
    _mtokenPromise = (async () => {
      try {
        const r = await fetch(modstoreBase() + '/api/auth/login', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: global.XCAGI_MODSTORE_USER || 'admin',
            password: global.XCAGI_MODSTORE_PASS || 'admin123',
          }),
        });
        if (!r.ok) return null;
        const j = await r.json();
        return j.access_token || j.token || null;
      } catch (_e) { return null; }
    })();
    return _mtokenPromise;
  }
  async function modstoreGet(nativePath) {
    if (!isLocalHost()) return null;
    const tok = await modstoreToken();
    if (!tok) return null;
    try {
      const r = await fetch(modstoreBase() + nativePath, { headers: { Accept: 'application/json', Authorization: 'Bearer ' + tok } });
      if (!r.ok) return null;
      return await r.json();
    } catch (_e) { return null; }
  }
  /** 先走 FHD 同源代理；为空则 localhost 跨源直连 MODstore 原生路径 */
  async function fetchActionItems(kind) {
    const fhd = await fetchJson(`/api/xcmax/admin/action-items?kind=${kind}`);
    if (fhd && (fhd.data || fhd.items)) return fhd;
    const native = await modstoreGet(`/api/admin/action-items?kind=${kind}`);
    return native || fhd;
  }
  async function fetchActionStats(kind) {
    const fhd = await fetchJson(`/api/xcmax/admin/action-items/stats?kind=${kind}`);
    if (fhd && (fhd.data || fhd.total != null)) return fhd;
    const native = await modstoreGet(`/api/admin/action-items/stats?kind=${kind}`);
    return native || fhd;
  }

  function ensureStyles() {
    if (document.getElementById('ai-action-items-style')) return;
    const css = `
.ai-board{margin:0 0 22px}
.ai-board-panel{border:1px solid var(--border,rgba(120,180,255,.2));border-radius:12px;padding:16px 20px;margin-bottom:14px;background:var(--bg2,rgba(16,24,40,.5))}
.ai-board-panel-title{font-size:14px;font-weight:700;color:var(--cyan,#58e2c2);margin-bottom:6px}
.ai-board-panel-desc{font-size:11px;color:var(--muted,#86a0bd);line-height:1.6}
.ai-board-refresh{margin-left:8px;background:transparent;color:var(--cyan,#58e2c2);border:1px solid var(--border2,rgba(88,226,194,.4));border-radius:5px;padding:1px 9px;font-size:10px;cursor:pointer}
.ai-sum{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px}
.ai-sum-box{padding:12px 16px;border-radius:8px;display:flex;align-items:center;gap:10px}
.ai-sum-emoji{font-size:24px}
.ai-sum-num{font-size:18px;font-weight:700;font-family:'Space Grotesk',sans-serif;line-height:1}
.ai-sum-label{font-size:10px;color:var(--muted,#86a0bd);letter-spacing:1px;margin-top:2px}
.ai-grp-title{font-size:12px;font-weight:700;color:var(--muted,#9fb6d6);letter-spacing:.5px;margin:14px 0 8px}
.gap-card.ai-fixed{display:flex;flex-direction:column}
.gap-card.ai-fixed.resolved{opacity:.55;border-style:dashed;filter:saturate(.75)}
.gap-card.ai-fixed.resolved .gap-name{color:var(--muted,#86a0bd);text-decoration:line-through;text-decoration-color:rgba(134,160,189,.45)}
.ai-card-head{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.ai-status-badge{margin-left:auto;font-size:10px;font-weight:600;padding:1px 8px;border-radius:6px;background:rgba(120,180,255,.15);color:var(--muted,#86a0bd)}
.ai-status-badge.merged,.ai-status-badge.closed{background:rgba(86,211,100,.18);color:var(--green,#56d364)}
.ai-status-badge.in_progress{background:rgba(255,166,87,.15);color:var(--orange,#ffa657)}
.ai-status-badge.dispatched{background:rgba(121,192,255,.15);color:var(--blue,#79c0ff)}
.ai-fields{margin:8px 0 0;display:grid;grid-template-columns:1fr 1fr;gap:3px 12px}
.ai-field{display:flex;gap:6px;font-size:11px;line-height:1.55}
.ai-field dt{color:var(--muted,#86a0bd);min-width:52px;flex:0 0 auto}
.ai-field dd{margin:0;color:var(--text,#dce8fb);word-break:break-all}
.ai-field dd code{font-size:10px}
`;
    const st = document.createElement('style');
    st.id = 'ai-action-items-style';
    st.textContent = css;
    document.head.appendChild(st);
  }

  function resolvePriority(it, kind) {
    let p = String((it && it.priority) || '').trim();
    if (p) return p;
    const t = String((it && it.text) || '');
    const m = t.match(/\*\*P([0-3])\*\*/) || t.match(/\bP([0-3])\b/);
    if (m) return 'P' + m[1];
    return kind === 'patch' ? 'P2' : 'P1';
  }

  function priClass(p, done) {
    if (done) return 'ok';
    return p === 'P0' ? 'p0' : p === 'P1' ? 'p1' : p === 'P2' ? 'p2' : 'p3';
  }

  /** 清洗条目文本：去 **Pn** 前缀；把原始失败 dict 提炼成 task 摘要 */
  function cleanText(t) {
    let s = String(t || '');
    s = s.replace(/\*\*P[0-3]\*\*/g, '').replace(/^\s*P[0-3]\s*[·:：]?\s*/, '');
    const tm = s.match(/'task'\s*:\s*'([^']+)'/);
    if (tm) {
      const head = s.split('{')[0].trim().replace(/[:：]\s*$/, '');
      s = (head ? head + '：' : '') + tm[1];
    }
    return s.replace(/\s+/g, ' ').trim();
  }

  /** 固定字段模板：每条卡片统一栏位（优先级/责任员工/产线/范围/状态/日期） */
  function cardHtml(it, kind) {
    const done = !!DONE[it.status];
    const priority = resolvePriority(it, kind);
    const pcls = priClass(priority, done);
    const plabel = done ? '✅ 已闭环' : priority;
    const name = cleanText(it.text) || '(无描述)';
    const emp = it.employee_label || it.employee_id || '—';
    const st = String(it.status || 'open');
    const stLabel = STATUS_LABEL[st] || st;
    const fields = [
      ['责任员工', esc(emp)],
      ['产线', esc(LINE_LABEL[it.line] || it.line || '—')],
      ['优先级', esc(priority)],
      ['状态', esc(stLabel)],
      ['范围', it.scope_path ? `<code>${esc(it.scope_path)}</code>` : '—'],
      ['日期', esc(it.day || '—')],
    ];
    const fieldsHtml = fields
      .map(([k, v]) => `<div class="ai-field"><dt>${k}</dt><dd>${v}</dd></div>`)
      .join('');
    return (
      `<div class="gap-card ai-fixed${done ? ' resolved' : ''}">` +
      `<div class="ai-card-head">` +
      `<span class="gap-pri ${pcls}">${esc(plabel)}</span>` +
      `<span class="ai-status-badge ${esc(st)}">${esc(stLabel)}</span>` +
      `</div>` +
      `<div class="gap-name">${esc(name)}</div>` +
      `<dl class="ai-fields">${fieldsHtml}</dl>` +
      `</div>`
    );
  }

  function gridHtml(items, groupBy, kind) {
    if (!items.length) return '<div class="ai-board-panel-desc">今日暂无条目（触发 digest 后刷新）。</div>';
    const groups = {};
    for (const it of items) {
      const k = groupBy === 'priority' ? resolvePriority(it, kind) : (it.line || 'P-S');
      (groups[k] = groups[k] || []).push(it);
    }
    let keys = Object.keys(groups);
    if (groupBy === 'priority') keys.sort((a, b) => PRIORITY_ORDER.indexOf(a) - PRIORITY_ORDER.indexOf(b));
    else keys.sort();
    return keys
      .map((k) => {
        const label = groupBy === 'priority' ? (k === '其他' ? '其他' : k) : (LINE_LABEL[k] || k);
        return `<div class="ai-grp-title">${esc(label)} · ${groups[k].length}</div>` +
          `<div class="gap-grid">${groups[k].map((it) => cardHtml(it, kind)).join('')}</div>`;
      })
      .join('');
  }

  function sumBox(emoji, num, label, varName) {
    const c = `var(${varName})`;
    const rgb = { '--red': '248,81,73', '--orange': '255,166,87', '--purple': '210,168,255', '--green': '86,211,100', '--blue': '121,192,255', '--cyan': '88,226,194' }[varName] || '120,180,255';
    return (
      `<div class="ai-sum-box" style="background:linear-gradient(135deg,rgba(${rgb},0.12),rgba(${rgb},0.04));border:1px solid rgba(${rgb},0.3)">` +
      `<div class="ai-sum-emoji">${emoji}</div>` +
      `<div><div class="ai-sum-num" style="color:${c}">${esc(num)}</div><div class="ai-sum-label">${esc(label)}</div></div>` +
      `</div>`
    );
  }

  async function renderBoard(opts) {
    ensureStyles();
    const section = document.getElementById(opts.sectionId);
    if (!section) return;
    let board = section.querySelector('#' + opts.boardId);
    if (!board) {
      board = document.createElement('div');
      board.id = opts.boardId;
      board.className = 'ai-board';
      const firstChild = section.firstElementChild;
      if (firstChild && firstChild.nextSibling) section.insertBefore(board, firstChild.nextSibling);
      else section.insertBefore(board, section.firstChild);
    }
    board.innerHTML = '<div class="ai-board-panel-desc">加载日更条目…</div>';

    const [list, statsResp] = await Promise.all([
      fetchActionItems(opts.kind),
      fetchActionStats(opts.kind),
    ]);
    const data = list && (list.data || list);
    const items = (data && (data.items || (data.data && data.data.items))) || [];
    const day = (data && (data.day || (data.data && data.data.day))) || '';
    const sraw = (statsResp && (statsResp.data || statsResp)) || {};
    const sd = sraw.data || sraw;
    if (!data) {
      board.innerHTML =
        `<div class="ai-board-panel"><div class="ai-board-panel-title">${esc(opts.title)}</div>` +
        '<div class="ai-board-panel-desc">需管理员会话或本地 MODstore（FHD 以本地自动化启动后自动出数据）。</div></div>';
      return;
    }
    const byP = sd.by_priority || {};
    const total = sd.total != null ? sd.total : items.length;
    const summary =
      opts.kind === 'patch'
        ? sumBox('🔴', byP.P0 || 0, 'P0 紧急修复', '--red') +
          sumBox('🟠', (byP.P1 || 0) + (byP.P2 || 0), 'P1/P2 待办', '--orange') +
          sumBox('🟢', (sd.completion_rate || 0) + '%', '完成率 · 已闭环 ' + (sd.done || 0), '--green')
        : sumBox('🔵', total, '更新条目', '--blue') +
          sumBox('🟣', Object.keys(sd.by_line || {}).length, '覆盖产线', '--purple') +
          sumBox('🟢', (sd.completion_rate || 0) + '%', '完成率 · 已落 ' + (sd.done || 0), '--green');

    board.innerHTML =
      `<div class="ai-board-panel">` +
      `<div class="ai-board-panel-title">${esc(opts.title)}` +
      `<button type="button" class="ai-board-refresh">刷新</button></div>` +
      `<div class="ai-board-panel-desc">${esc(day || '—')} · release_train <code>${esc((sd.rt_version) || (items[0] && items[0].rt_version) || '')}</code> · 共 ${esc(total)} 条 · 源自 V 节点「Vibe 预备 ${opts.kind === 'patch' ? '补丁' : '更新'} MD」· 状态随 line-execute 流转</div>` +
      `</div>` +
      `<div class="ai-sum">${summary}</div>` +
      gridHtml(items, opts.groupBy, opts.kind);
    const btn = board.querySelector('.ai-board-refresh');
    if (btn) btn.addEventListener('click', () => renderBoard(opts));
  }

  function renderPatches(force) {
    if (rendered.patch && !force) return;
    if (force) rendered.patch = false;
    rendered.patch = true;
    renderBoard({ kind: 'patch', sectionId: 's-gaps', boardId: 'ai-patch-board', title: '🤖 今日 AI 补丁清单 · 自动驱动断点闭环', groupBy: 'priority' });
  }
  function renderUpdates(force) {
    if (rendered.update && !force) return;
    if (force) rendered.update = false;
    rendered.update = true;
    renderBoard({ kind: 'update', sectionId: 's-roadmap', boardId: 'ai-update-board', title: '🤖 今日 AI 更新清单 · 自动推进路线图', groupBy: 'line' });
  }

  /** 清理旧版静态面板（多来源遗留：s-deep-closure / 手写 gap-grid / 旧计数盒） */
  function purgeLegacyStaticPanels() {
    try {
      ['s-deep-closure'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.remove();
      });
      const gaps = document.getElementById('s-gaps');
      if (gaps) {
        gaps.querySelectorAll(':scope > .gap-grid').forEach((el) => {
          if (!el.closest('#ai-patch-board')) el.remove();
        });
        gaps.querySelectorAll(':scope > div[style*="grid-template-columns:repeat(3"]').forEach((el) => el.remove());
      }
      const road = document.getElementById('s-roadmap');
      if (road) {
        road.querySelectorAll(':scope > .phase-grid, :scope > div[style*="margin:24px 0"]').forEach((el) => {
          if (!el.closest('#ai-update-board')) el.remove();
        });
      }
    } catch (_e) { /* 静默 */ }
  }

  function boot() {
    try {
      purgeLegacyStaticPanels();
      if (document.getElementById('s-gaps')) renderPatches(false);
      if (document.getElementById('s-roadmap')) renderUpdates(false);
      document.addEventListener('click', (e) => {
        const t = e.target;
        if (!t || !t.closest) return;
        if (t.closest('[data-section="gaps"],[href="#s-gaps"],#nav-gaps')) setTimeout(() => renderPatches(true), 60);
        if (t.closest('[data-section="roadmap"],[href="#s-roadmap"],#nav-roadmap')) setTimeout(() => renderUpdates(true), 60);
      });
      // 切 Tab / 后台回写后自动刷新（30s，仅 localhost 调试栈）
      if (isLocalHost()) {
        setInterval(() => {
          const gapsVis = document.getElementById('s-gaps') && !document.getElementById('s-gaps').hidden;
          const roadVis = document.getElementById('s-roadmap') && !document.getElementById('s-roadmap').hidden;
          if (gapsVis) renderPatches(true);
          if (roadVis) renderUpdates(true);
        }, 30000);
      }
    } catch (_e) { /* 静默降级 */ }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  global.EmpWfActionItems = { renderPatches, renderUpdates };
})(typeof window !== 'undefined' ? window : globalThis);
