/**
 * 日更闭环 · 阶段结果文件面板
 * 读取最新 DailyDigestRecord 的各阶段产物（截图 PNG / PPT / digest HTML / 会议 / Vibe MD /
 * release_train 历史快照 / 容灾备份），渲染到 #emp-wf-stage-artifacts。
 * 数据：FHD /api/xcmax/admin/daily-digests(+/{id}/artifacts)（本地 MODstore :8788 优先）。
 */
(function (global) {
  'use strict';

  const ROOT_ID = 'emp-wf-stage-artifacts';
  let loaded = false;

  function api(path) {
    return global.XCAGIApi ? global.XCAGIApi.url(path) : path;
  }

  function fmtBytes(n) {
    n = Number(n || 0);
    if (n <= 0) return '0';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(2) + ' MB';
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]),
    );
  }

  async function fetchJson(path) {
    try {
      const r = await fetch(api(path), { headers: { Accept: 'application/json' }, credentials: 'include' });
      if (!r.ok) return null;
      const ct = (r.headers.get('content-type') || '').toLowerCase();
      if (ct.includes('text/html')) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

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
  async function fetchDigestList() {
    const fhd = await fetchJson('/api/xcmax/admin/daily-digests?limit=1');
    if (fhd && (fhd.data || Array.isArray(fhd))) return fhd;
    const native = await modstoreGet('/api/agent/butler/daily-digests?limit=1');
    return native || fhd;
  }
  async function fetchDigestArtifacts(recordId) {
    const fhd = await fetchJson(`/api/xcmax/admin/daily-digests/${recordId}/artifacts`);
    if (fhd && (fhd.data || fhd.stages)) return fhd;
    const native = await modstoreGet(`/api/agent/butler/daily-digests/${recordId}/artifacts`);
    return native || fhd;
  }

  function fileListHtml(files, kind) {
    if (!files || !files.length) return '<div class="sa-empty">（无文件）</div>';
    const rows = files
      .slice(0, 30)
      .map((f) => {
        const meta = [f.bytes != null ? fmtBytes(f.bytes) : '', f.mtime ? String(f.mtime).slice(0, 19).replace('T', ' ') : '']
          .filter(Boolean)
          .join(' · ');
        const tag = kind === 'image_dir' ? '🖼' : kind === 'backup_dir' ? '💾' : '📄';
        return `<li><span class="sa-file-name">${tag} ${esc(f.name)}</span><span class="sa-file-meta">${esc(meta)}</span></li>`;
      })
      .join('');
    return `<ul class="sa-file-list">${rows}</ul>`;
  }

  function rtHtml(stage) {
    if (stage.error) return `<div class="sa-empty">读取失败：${esc(stage.error)}</div>`;
    const snap = stage.snapshot || {};
    const hist = stage.history || [];
    const head = `<div class="sa-rt-head">当前 <code>${esc(snap.current || '?')}</code> · day_index ${esc(snap.day_index)} · 本跑 ${esc(stage.before)} → <code>${esc(stage.after)}</code> (${esc(stage.release_kind || 'daily')}) · 幂等日 ${esc(snap.last_bump_day || '—')}</div>`;
    const rows = hist
      .slice(0, 12)
      .map(
        (h) =>
          `<li><span class="sa-file-name">${esc(h.reason || '')} → <code>${esc(h.current || '')}</code></span><span class="sa-file-meta">${esc((h.saved_at || '').slice(0, 19).replace('T', ' '))}</span></li>`,
      )
      .join('');
    return head + (rows ? `<ul class="sa-file-list">${rows}</ul>` : '<div class="sa-empty">（暂无历史快照）</div>');
  }

  function mdFieldsHtml(stage) {
    const rows = (stage.fields || [])
      .map(
        (f) =>
          `<li><span class="sa-file-name">${esc(f.label)}</span><span class="sa-file-meta">${f.bytes ? fmtBytes(f.bytes) : '空'}</span></li>`,
      )
      .join('');
    return `<ul class="sa-file-list">${rows}</ul>`;
  }

  function stageCardHtml(stage) {
    let body;
    if (stage.kind === 'release_train') body = rtHtml(stage);
    else if (stage.kind === 'md_fields') body = mdFieldsHtml(stage);
    else if (stage.kind === 'html_field')
      body = `<div class="sa-empty">${stage.bytes ? fmtBytes(stage.bytes) + ' HTML' : '（空）'}</div>`;
    else if (stage.kind === 'db_record')
      body = `<div class="sa-rt-head">${esc(stage.subject || '')}<br>HTML ${fmtBytes(stage.body_html_bytes)} · 文本 ${fmtBytes(stage.body_text_bytes)} · 投递 ${stage.delivered ? '✅' : '—'}</div>`;
    else if (stage.error) body = `<div class="sa-empty">读取失败：${esc(stage.error)}</div>`;
    else body = `<div class="sa-dir">${esc(stage.dir || '')}</div>` + fileListHtml(stage.files, stage.kind);
    const count = stage.count != null ? ` <span class="sa-badge">${stage.count}</span>` : '';
    return `<div class="sa-card"><div class="sa-card-head"><span class="sa-node">${esc(stage.node)}</span><span class="sa-label">${esc(stage.label)}</span>${count}</div><div class="sa-card-body">${body}</div></div>`;
  }

  async function render(force) {
    const root = document.getElementById(ROOT_ID);
    if (!root) return;
    if (loaded && !force) return;
    loaded = true;
    root.innerHTML = '<div class="sa-loading">加载日更各阶段结果文件…</div>';

    const list = await fetchDigestList();
    const rows = list && (list.data || list);
    const rec = Array.isArray(rows) ? rows[0] : rows && rows.data && rows.data[0];
    if (!rec || rec.id == null) {
      root.innerHTML =
        '<div class="sa-empty">暂无 DailyDigestRecord（启动本地 MODstore :8788 并触发 digest-now 后刷新）。</div>';
      return;
    }
    const art = await fetchDigestArtifacts(rec.id);
    const data = art && (art.data || art);
    if (!data || !data.stages) {
      root.innerHTML = '<div class="sa-empty">artifacts 接口无数据（需管理员会话或本地 MODstore）。</div>';
      return;
    }
    const head = `<div class="sa-head">记录 #${esc(data.record_id)} · ${esc(data.day)} · <button type="button" class="sa-refresh">刷新</button></div>`;
    const cards = data.stages.map(stageCardHtml).join('');
    root.innerHTML = head + `<div class="sa-grid">${cards}</div>`;
    const btn = root.querySelector('.sa-refresh');
    if (btn) btn.addEventListener('click', () => render(true));
  }

  function boot() {
    // 时间轨 Tab 默认展示；若被懒激活，监听 hash/click 再渲染
    if (document.getElementById(ROOT_ID)) render(false);
    document.addEventListener('click', (e) => {
      const t = e.target;
      if (t && t.closest && t.closest('[data-section="workflow"],[href="#s-workflow"],#nav-workflow')) {
        setTimeout(() => render(false), 60);
      }
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  global.EmpWfStageArtifacts = { render };
})(typeof window !== 'undefined' ? window : globalThis);
