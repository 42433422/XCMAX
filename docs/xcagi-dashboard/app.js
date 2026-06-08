/* ==========================================================================
 * XCAGI v9.0.0 · Dashboard Application
 * 模块化拆分（替代原 173KB 单文件中的内联 JS）
 *
 *  Modules:
 *    - utils        : escapeHtml / fmtSize / 文件扩展名工具
 *    - router       : go() / Tab 切换 (a11y: Arrow keys, Home/End)
 *    - ops          : 运营线健康检查 / 步骤权重 / 实时刷新
 *    - tree         : 30K 文件目录树 (主线程仅做渲染, 重计算在 worker)
 *    - gaps         : 断点清单折叠 + 虚拟滚动
 *    - init         : 入口与事件绑定
 *
 *  严格模式 + 不依赖任何外部库
 * ========================================================================== */
'use strict';

/* ==========================================================================
 * 1. utils — 通用工具与安全转义
 * ========================================================================== */
const Utils = (() => {
  const HTML_ESCAPE = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;' };
  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"'`]/g, (c) => HTML_ESCAPE[c]);
  }
  function escapeAttr(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, (c) => HTML_ESCAPE[c]);
  }
  function fmtSize(n) {
    if (n == null) return '';
    if (n < 1024) return n + 'B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + 'KB';
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + 'MB';
    return (n / 1024 / 1024 / 1024).toFixed(2) + 'GB';
  }
  function fileExt(name) {
    const n = String(name).toLowerCase();
    if (!n.includes('.')) return '';
    return '.' + n.split('.').pop();
  }
  function debounce(fn, ms) {
    let t = null;
    return function () {
      const args = arguments;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), ms);
    };
  }
  function safeText(el, text) {
    if (!el) return;
    el.textContent = text == null ? '' : String(text);
  }
  function setMultiText(el, parts) {
    if (!el) return;
    el.replaceChildren();
    parts.forEach((p) => {
      if (p == null) return;
      if (typeof p === 'string') el.appendChild(document.createTextNode(p));
      else if (p instanceof Node) el.appendChild(p);
    });
  }
  return { escapeHtml, escapeAttr, fmtSize, fileExt, debounce, safeText, setMultiText };
})();

/** 静态 JSON：嵌入 FHD 时走 XCAGIApi.fetchJson，避免 SPA index.html 被当 JSON 解析 */
async function dashFetchJson(resource, init) {
  if (window.XCAGIApi && typeof window.XCAGIApi.fetchJson === 'function') {
    return window.XCAGIApi.fetchJson(resource, init);
  }
  try {
    const r = await fetch(resource, init);
    if (!r.ok) return null;
    const ct = (r.headers.get('content-type') || '').toLowerCase();
    if (ct.includes('text/html')) return null;
    return await r.json();
  } catch {
    return null;
  }
}

/* ==========================================================================
 * 2. router — 顶部 Tab 切换 (含 a11y 键盘导航)
 * ========================================================================== */
const Router = (() => {
  const VALID = new Set(['loops', 'workflow', 'events', 'monitor', 'aibiz', 'tree', 'gaps', 'roadmap', 'evolution']);

  function notifyTab(tabId) {
    try {
      document.dispatchEvent(new CustomEvent('xcagi-tab-shown', { detail: { tab: tabId } }));
    } catch (_) { /* IE11 */ }
  }

  function show(id, opts = {}) {
    if (!VALID.has(id)) id = 'loops';
    const panelId = id;
    const target = document.getElementById('s-' + panelId);
    if (!target) return;
    document.querySelectorAll('.section').forEach((s) => {
      s.classList.toggle('active', s === target);
      if (s.id && s.id.startsWith('s-')) {
        const on = s === target;
        s.hidden = !on;
        s.setAttribute('aria-hidden', on ? 'false' : 'true');
      }
    });
    document.querySelectorAll('.nav-btn').forEach((b) => {
      const isActive = b.dataset.tab === id;
      b.classList.toggle('active', isActive);
      if (isActive) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
    if (id === 'gaps') Gaps.activate();
    if (id === 'tree') Tree.activate();
    if (id === 'events') {
      document.body.classList.remove('embed-workflow');
      EventRail.activate();
      notifyTab(id);
      if (!opts.skipScroll) {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
      return;
    }
    if (id === 'workflow') {
      if (document.body.classList.contains('embed-shell')) {
        document.body.classList.add('embed-workflow');
      }
      EmployeeWorkflow.activate();
      notifyTab(id);
      if (!opts.skipScroll) {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
      return;
    }
    document.body.classList.remove('embed-workflow');
    notifyTab(id);
    if (!opts.skipScroll) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

  function bind() {
    const nav = document.querySelector('.nav-inner');
    if (!nav) return;
    nav.querySelectorAll('.nav-btn').forEach((btn, idx, all) => {
      const id = (btn.getAttribute('onclick') || '').match(/go\('([^']+)'\)/);
      if (id) btn.dataset.tab = id[1];
      btn.removeAttribute('onclick');
      btn.addEventListener('click', () => show(btn.dataset.tab));
      btn.addEventListener('keydown', (e) => {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft' && e.key !== 'Home' && e.key !== 'End') return;
        e.preventDefault();
        let next = idx;
        if (e.key === 'ArrowRight') next = (idx + 1) % all.length;
        else if (e.key === 'ArrowLeft') next = (idx - 1 + all.length) % all.length;
        else if (e.key === 'Home') next = 0;
        else next = all.length - 1;
        all[next].focus();
        show(all[next].dataset.tab);
      });
    });
  }

  // 兼容原 onClick="go('xxx')"
  window.go = (id) => show(id);

  return { show, bind };
})();

/* ==========================================================================
 * 3. ops — 运营线健康检查
 * ========================================================================== */
const Ops = (() => {
  const TAG_LABEL = { done: '已做', partial: '部分', blocked: '待补' };
  const STEP_WEIGHTS = { O1: 1, O2: 0.95, O3: 0.82, O4: 0.95, O5: 1, O6: 1, O7: 0.95, O8: 0.95, O9: 0.95, O10: 0.9 };

  function modstoreBase() {
    if (window.XCAGI_MODSTORE_URL) {
      return String(window.XCAGI_MODSTORE_URL).replace(/\/$/, '');
    }
    if (window.XCAGIApi && window.XCAGIApi.isFhdEmbed) {
      return 'http://127.0.0.1:8788';
    }
    return (window.XCAGI_OPS_HEALTH_URL || 'http://127.0.0.1:8765').replace(/\/$/, '');
  }

  function healthBase() {
    return modstoreBase();
  }

  function applyStepStatus(steps) {
    if (!steps || typeof steps !== 'object') return;
    let totalPct = 0;
    for (let i = 1; i <= 10; i++) {
      const sid = 'O' + i;
      const st = (steps[sid] && steps[sid].status) || 'partial';
      const w = STEP_WEIGHTS[sid] || 0.5;
      if (st === 'done') totalPct += 1;
      else if (st === 'blocked') totalPct += 0;
      else totalPct += w;
      const node = document.querySelector('.ops-step-node[data-ops-step="' + sid + '"]');
      if (!node) continue;
      const dot = node.querySelector('.node-dot');
      const tag = node.querySelector('.node-tag');
      const cls = st === 'done' ? 'done' : st === 'blocked' ? 'missing' : 'partial';
      if (dot) {
        dot.classList.remove('done', 'partial', 'missing');
        dot.classList.add(cls);
      }
      if (tag) {
        tag.classList.remove('done', 'partial', 'missing');
        tag.classList.add(cls);
        Utils.safeText(tag, TAG_LABEL[st] || '部分');
      }
    }
    const el = document.getElementById('ops-loop-progress-num');
    if (el) Utils.safeText(el, Math.round((totalPct / 10) * 100) + '%');
  }

  function buildHealthUrls() {
    const isFile = location.protocol === 'file:';
    const port = location.port || '';
    const host = location.hostname || '';
    const origin = !isFile ? (location.origin || '').replace(/\/$/, '') : '';
    const urls = [];
    if (origin) urls.push(origin + '/api/operations-line/health');
    /* 桌面壳 iframe（5003）仅用同源 API，勿回退 MODstore/FHD 直连，避免 CORS 与控制台噪音 */
    const embedOnDesktop =
      !isFile && (host === '127.0.0.1' || host === 'localhost') && port === '5003';
    if (!embedOnDesktop) {
      const modBase = modstoreBase();
      if (modBase && modBase !== origin) {
        urls.push(modBase + '/api/admin/production-line/operations-health');
      }
      /* file:// 无法同源；其余场景依赖 dashboard 开发服 /api 反代，勿跨域打 :5000 */
      if (isFile) urls.push('http://127.0.0.1:5000/api/operations-line/health');
    }
    return urls;
  }

  function normalizeHealthPayload(json) {
    if (!json || typeof json !== 'object') return null;
    if (json.ok === false && json.success === false) return null;
    let inner = json.data;
    if (inner && inner.data && inner.data.steps) inner = inner.data;
    if (inner && inner.steps) return inner;
    if (json.steps) return json;
    return null;
  }

  async function fetchHealth() {
    const isFile = location.protocol === 'file:';
    const bases = buildHealthUrls();
    const sameOriginFirst = !isFile && bases.length && bases[0].startsWith(location.origin);
    const timeoutMs = sameOriginFirst ? 10000 : 2500;
    let lastErr = null;
    for (const url of bases) {
      const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
      const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
      try {
        const opts = { credentials: isFile ? 'omit' : 'include' };
        if (ctrl) opts.signal = ctrl.signal;
        const resp = await fetch(url, opts);
        if (resp.status === 403) throw new Error('HTTP 403 (需登录或CSRF)');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const json = await resp.json();
        const payload = normalizeHealthPayload(json);
        if (!payload) throw new Error('bad payload');
        return { source: url, payload };
      } catch (e) {
        lastErr = e;
      } finally {
        if (timer) clearTimeout(timer);
      }
    }
    throw lastErr || new Error('health fetch failed');
  }

  /* 用 DOM 构造（不再 innerHTML 拼接用户可控字段） */
  function renderMetaOk(source, payload) {
    const meta = document.getElementById('ops-live-meta');
    if (!meta) return;
    meta.replaceChildren();
    const at = payload.generated_at || new Date().toISOString();
    const pc = payload.pipeline_count != null ? payload.pipeline_count : '—';
    const bp = payload.breakpoint_count != null ? payload.breakpoint_count : '—';
    const ext = payload.external_crm_configured ? ' · 外部CRM已配置' : '';
    const pay = payload.payment_backend ? ' · 支付:' + payload.payment_backend : '';

    const head = document.createElement('strong');
    head.textContent = '来源 ';
    meta.appendChild(head);
    meta.appendChild(document.createTextNode(source.split('/api/')[0] + ' · 刷新 ' + at.slice(0, 19).replace('T', ' ') + ' · pipeline '));
    const b1 = document.createElement('strong');
    b1.textContent = String(pc);
    meta.appendChild(b1);
    meta.appendChild(document.createTextNode(' · CRM/ERP缺口 '));
    const b2 = document.createElement('strong');
    b2.textContent = String(bp);
    meta.appendChild(b2);
    if (ext) meta.appendChild(document.createTextNode(ext));
    if (pay) meta.appendChild(document.createTextNode(pay));
  }

  function setLiveUi(state, metaText) {
    const badge = document.getElementById('ops-live-badge');
    const meta = document.getElementById('ops-live-meta');
    const refreshBtn = document.getElementById('btn-refresh-health');
    const bar = document.getElementById('ops-live-bar');
    if (bar) {
      bar.classList.remove('ok', 'warn', 'err');
      bar.classList.add(state);
    }
    if (badge) {
      badge.className = 'ops-live-status ' + (state === 'ok' ? 'ok' : state === 'warn' ? 'warn' : 'err');
      badge.textContent = state === 'ok' ? 'Live' : state === 'warn' ? '静态' : '离线';
    }
    if (meta) {
      if (metaText instanceof Node) {
        meta.replaceChildren(metaText);
      } else if (typeof metaText === 'string') {
        // 静态 fallback 文案，全部来自内部常量 → 安全
        meta.textContent = metaText;
      }
    }
    if (refreshBtn) refreshBtn.textContent = state === 'ok' ? '🔄 刷新' : '🔄 连接服务';
  }

  function renderMetaWarn(tip, errMsg) {
    const meta = document.getElementById('ops-live-meta');
    if (!meta) return;
    meta.replaceChildren();
    meta.appendChild(document.createTextNode(tip + (errMsg ? ' (' + errMsg + ')' : '') + ' · 当前显示代码库静态现状'));
  }

  async function refresh() {
    const btn = document.getElementById('btn-refresh-health');
    if (btn) btn.disabled = true;
    try {
      const { source, payload } = await fetchHealth();
      applyStepStatus(payload.steps || {});
      renderMetaOk(source, payload);
      setLiveUi('ok', null);
    } catch (e) {
      const isFile = location.protocol === 'file:';
      let errMsg = e && e.message ? e.message : '';
      if (e && e.name === 'AbortError') errMsg = '请求超时(1.5s)';
      const tip = isFile
        ? '当前以 file:// 打开，跨域受限。请用 http-server 或 python -m http.server 托管后访问'
        : '服务未启动或需登录。请确认 FHD :5100/:5000 与 MODstore :8788 已运行';
      renderMetaWarn(tip, errMsg);
      setLiveUi('warn', null);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function processOutbox() {
    const btn = document.getElementById('btn-process-outbox');
    if (btn) btn.disabled = true;
    try {
      const url = healthBase() + '/api/admin/production-line/webhook-outbox/process?limit=20';
      const resp = await fetch(url, { method: 'POST', credentials: 'include' });
      const json = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error((json && json.message) || 'HTTP ' + resp.status);
      // alert 的内容是后端 JSON 文本，使用 textContent 方式输出更安全
      window.alert('Outbox 已处理: ' + JSON.stringify(json.data || json || {}));
      await refresh();
    } catch (e) {
      window.alert('Outbox 处理失败: ' + (e && e.message ? e.message : String(e)));
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function bind() {
    const refreshBtn = document.getElementById('btn-refresh-health');
    if (refreshBtn) refreshBtn.addEventListener('click', refresh);
    const outboxBtn = document.getElementById('btn-process-outbox');
    if (outboxBtn) outboxBtn.addEventListener('click', processOutbox);
  }

  return { refresh, processOutbox, bind, setLiveUi, applyStepStatus };
})();

/* ==========================================================================
 * 4. tree — 30K 文件目录树 (主线程只做渲染，重计算在 worker)
 * ========================================================================== */
const Tree = (() => {
  const GLYPH_MAP = {
    '.py': 'g-py', '.ts': 'g-js', '.tsx': 'g-js', '.js': 'g-js',
    '.mjs': 'g-js', '.cjs': 'g-js', '.vue': 'g-vue',
    '.json': 'g-cfg', '.yml': 'g-cfg', '.yaml': 'g-cfg', '.toml': 'g-cfg',
    '.md': 'g-doc', '.txt': 'g-doc',
    '.html': 'g-web', '.css': 'g-web', '.scss': 'g-web',
    '.xlsx': 'g-data', '.xls': 'g-data', '.csv': 'g-data', '.docx': 'g-data', '.pdf': 'g-data',
    '.png': 'g-img', '.jpg': 'g-img', '.svg': 'g-img', '.ico': 'g-img',
    '.sql': 'g-sql',
    '.sh': 'g-sh', '.bat': 'g-sh', '.btw': 'g-data', '.asar': 'g-data',
  };
  const NAME_CLS = GLYPH_MAP;

  const state = {
    expanded: new Set(),
    filter: '',
    ext: '',
    pathMap: new Map(),
    totalFiles: 0,
    totalDirs: 0,
    totalSize: 0,
    activated: false,
    lineCoverage: null,
    pathEmployee: null,
  };

  let worker = null;
  let pendingBuffer = [];
  let chunkTimer = null;

  function setStatus(html, busy) {
    const statusText = document.getElementById('tree-status-text');
    const spinner = document.getElementById('tree-spinner');
    if (statusText) statusText.textContent = html;
    if (spinner) spinner.style.display = busy ? 'inline-block' : 'none';
  }

  function ensureWorker() {
    if (worker) return worker;
    worker = new Worker('tree-worker.js');
    worker.addEventListener('message', onWorkerMessage);
    worker.addEventListener('error', (e) => {
      setStatus('❌ Worker 错误: ' + e.message, false);
    });
    return worker;
  }

  function onWorkerMessage(e) {
    const msg = e.data;
    if (msg.type === 'ready') {
      state.totalFiles = msg.rootMeta.totalFiles;
      state.totalDirs = msg.rootMeta.totalDirs;
      state.totalSize = msg.rootMeta.totalSize;
      state.lineCoverage = msg.rootMeta.lineCoverage || null;
      state.pathEmployee = msg.rootMeta.pathEmployee || null;
      if (state.lineCoverage) LineCoverage.renderPanel(state.lineCoverage);
      if (state.pathEmployee) LineCoverage.renderPathEmployeePanel(state.pathEmployee);
      console.log('[Tree] worker ready in ' + msg.rootMeta.loadSeconds + 's');
      // 自动展开 2 层
      const fakeRoot = { children: {} }; // 极简，2 层展开逻辑在主线程做
      // 让 worker 来做展开集合的初始化
      autoExpandLevels(2);
      requestRefresh();
    } else if (msg.type === 'chunk') {
      pendingBuffer = pendingBuffer.concat(msg.rows);
      // 用 rAF 节流避免高频插入
      if (!chunkTimer) {
        chunkTimer = requestAnimationFrame(flushBuffer);
      }
      if (msg.done) {
        // done
      }
    } else if (msg.type === 'stats') {
      state.totalFiles = msg.totalFiles;
      state.totalDirs = msg.totalDirs;
      state.totalSize = msg.totalSize;
      updateStats();
    } else if (msg.type === 'error') {
      setStatus('❌ ' + msg.message, false);
    }
  }

  function flushBuffer() {
    chunkTimer = null;
    if (!pendingBuffer.length) return;
    renderRows(pendingBuffer);
    pendingBuffer = [];
  }

  function autoExpandLevels(levels) {
    // 主线程只生成路径集合，不进行树遍历
    const root = document.getElementById('tree-render');
    if (!root || !state.pathMap.size) return;
    state.expanded.clear();
    state.pathMap.forEach((node, path) => {
      if (node.type !== 'dir') return;
      const depth = path.split('/').length;
      if (depth < levels) state.expanded.add(path);
    });
  }

  function requestRefresh() {
    if (!worker) return;
    worker.postMessage({
      type: 'filter',
      filter: state.filter,
      ext: state.ext,
      expanded: Array.from(state.expanded),
    });
  }

  function clearRender() {
    const root = document.getElementById('tree-render');
    if (!root) return;
    root.replaceChildren();
  }

  function renderRows(rows) {
    const root = document.getElementById('tree-render');
    if (!root) return;
    const frag = document.createDocumentFragment();
    for (const r of rows) {
      frag.appendChild(buildRow(r));
    }
    root.appendChild(frag);
    updateShown(rows.length);
  }

  function buildRow(r) {
    const row = document.createElement('div');
    row.className = 'tree-line' + (r.isDir ? ' is-dir' : ' is-file') + (r.isDir && r.expanded ? ' is-open' : '');
    row.style.setProperty('--depth', String(r.depth));
    row.dataset.path = r.path;
    // title 用 textContent 安全赋值
    row.title = 'XCMAX/' + r.path;
    row.setAttribute('role', r.isDir ? 'treeitem' : 'listitem');
    row.setAttribute('aria-expanded', r.isDir ? String(!!r.expanded) : 'false');
    if (r.isDir) row.tabIndex = 0;

    const main = document.createElement('div');
    main.className = 'tree-line-main';

    const caret = document.createElement('div');
    caret.className = 'tree-caret';
    if (r.isDir) caret.setAttribute('aria-hidden', 'true');
    main.appendChild(caret);

    const glyph = document.createElement('div');
    if (r.isDir) {
      glyph.className = 'tree-glyph is-folder';
      glyph.setAttribute('aria-hidden', 'true');
    } else {
      glyph.className = 'tree-glyph is-file ' + (GLYPH_MAP[Utils.fileExt(r.name)] || 'g-other');
      glyph.textContent = Utils.escapeHtml(glyphLabel(r.name));
    }
    main.appendChild(glyph);

    const name = document.createElement('div');
    name.className = 'tree-name' + (r.isDir ? '' : (' ' + (NAME_CLS[Utils.fileExt(r.name)] || '')));
    name.textContent = r.name;
    main.appendChild(name);

    if (r.lines && r.lines.length) {
      const tags = document.createElement('span');
      tags.className = 'tree-line-tags';
      for (const lid of r.lines) {
        const tag = document.createElement('span');
        tag.className = 'tree-line-tag ' + (LineCoverage.CLS[lid] || '');
        tag.textContent = LineCoverage.SHORT[lid] || lid;
        tags.appendChild(tag);
      }
      main.appendChild(tags);
    }

    if (r.primary && r.primary.length) {
      const staff = document.createElement('span');
      staff.className = 'tree-line-staff';
      staff.title = '主责员工';
      staff.textContent = r.primary.slice(0, 2).join(' · ') + (r.primary.length > 2 ? '…' : '');
      main.appendChild(staff);
    }

    row.appendChild(main);

    const countCol = document.createElement('div');
    countCol.className = 'tree-line-count';
    if (r.isDir) {
      const pill = document.createElement('span');
      pill.className = 'tree-pill';
      pill.textContent = (r.child.file_count || 0) + ' 文件';
      countCol.appendChild(pill);
    } else {
      const ext = Utils.fileExt(r.name);
      countCol.textContent = ext || '—';
    }
    row.appendChild(countCol);

    const sizeCol = document.createElement('div');
    sizeCol.className = 'tree-line-size';
    if (r.isDir) sizeCol.textContent = Utils.fmtSize(r.child.total_size);
    else if (r.child.size) sizeCol.textContent = Utils.fmtSize(r.child.size);
    row.appendChild(sizeCol);

    return row;
  }

  function glyphLabel(name) {
    const ext = Utils.fileExt(name);
    if (!ext) return '·';
    return ext.replace('.', '').slice(0, 4);
  }

  function updateShown(n) {
    const shownEl = document.getElementById('tt-shown');
    if (shownEl) shownEl.textContent = String(n);
    const colHead = document.getElementById('tree-col-head');
    if (colHead) colHead.hidden = n === 0;
  }

  function updateStats() {
    const dirsEl = document.getElementById('tt-dirs');
    const filesEl = document.getElementById('tt-files');
    const sizeEl = document.getElementById('tt-size');
    if (dirsEl) dirsEl.textContent = state.totalDirs.toLocaleString();
    if (filesEl) filesEl.textContent = state.totalFiles.toLocaleString();
    if (sizeEl) sizeEl.textContent = Utils.fmtSize(state.totalSize);
    const archTitle = document.getElementById('tree-arch-title');
    if (archTitle) {
      archTitle.textContent = 'XCMAX/ 工作区目录结构 · 2026-06-02 · ' + state.totalFiles.toLocaleString() + ' 个文件';
    }
    const ttTitle = document.querySelector('.tree-toolbar .tt-title');
    if (ttTitle) {
      ttTitle.textContent = '🌲 XCMAX/ 工作区 · ' + state.totalFiles.toLocaleString() + ' 文件';
    }
  }

  function bind() {
    const root = document.getElementById('tree-render');
    const search = document.getElementById('tree-search');
    const extSel = document.getElementById('tree-ext');
    if (!root) return;

    root.addEventListener('click', (e) => {
      const line = e.target.closest('.tree-line');
      if (!line) return;
      const path = line.dataset.path;
      const node = state.pathMap.get(path);
      if (node && node.type === 'dir') {
        if (state.expanded.has(path)) state.expanded.delete(path);
        else state.expanded.add(path);
        clearRender();
        requestRefresh();
      }
    });
    // 键盘展开/折叠
    root.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const line = e.target.closest('.tree-line');
      if (!line) return;
      e.preventDefault();
      line.click();
    });

    if (search) {
      const handler = Utils.debounce(() => {
        state.filter = search.value.trim();
        clearRender();
        requestRefresh();
      }, 150);
      search.addEventListener('input', handler);
    }
    if (extSel) {
      extSel.addEventListener('change', () => {
        state.ext = extSel.value;
        clearRender();
        requestRefresh();
      });
    }

    document.querySelectorAll('.tt-btn[data-act]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const act = btn.dataset.act;
        if (act === 'expand-all') {
          state.expanded = new Set(Array.from(state.pathMap.keys()).filter((p) => state.pathMap.get(p).type === 'dir'));
        } else if (act === 'collapse-all') {
          state.expanded.clear();
        } else if (act === 'expand-2') {
          autoExpandLevels(2);
        } else if (act === 'expand-3') {
          autoExpandLevels(3);
        }
        clearRender();
        requestRefresh();
      });
    });
  }

  function activate() {
    if (state.activated) return;
    state.activated = true;
    const root = document.getElementById('tree-render');
    if (!root) return;
    setStatus('⏳ 正在加载工作区目录树 (tree-worker.js + .cache/xcmax/xcmax-tree-data.json)…', true);
    ensureWorker();
    bind();
    worker.postMessage({ type: 'init', jsonUrl: '.cache/xcmax/xcmax-tree-data.json' });
    // worker 完成后会自动展开 + 渲染，状态文本在 ready 后清掉
    setTimeout(() => {
      const statusEl = document.getElementById('tree-status');
      if (statusEl) statusEl.style.display = 'none';
    }, 2000);
  }

  return { activate, bind, state };
})();

/* ==========================================================================
 * 5. gaps — 断点清单折叠 + 虚拟滚动
 * ========================================================================== */
const Gaps = (() => {
  const VIEWPORT = 480; // 卡片预估高度，px
  const OVERSCAN = 4;
  let activated = false;
  let cards = [];
  let container = null;

  function bindCollapsibles() {
    document.querySelectorAll('.node-gap--collapsible').forEach((wrap) => {
      const btn = wrap.querySelector('.node-gap-toggle');
      if (!btn || btn.dataset.gapBound) return;
      btn.dataset.gapBound = '1';
      btn.addEventListener('click', () => {
        wrap.classList.toggle('is-open');
        btn.textContent = wrap.classList.contains('is-open') ? '收起详情' : '展开详情';
      });
    });
  }

  function activate() {
    if (activated) return;
    activated = true;
    container = document.querySelector('#s-gaps .gap-grid');
    if (!container) return;
    bindCollapsibles();
    cards = Array.from(container.querySelectorAll('.gap-card'));
    if (cards.length < 30) return; // 卡片少就不上虚拟滚动
    setupVirtualScroll();
  }

  function setupVirtualScroll() {
    container.style.position = 'relative';
    const viewport = document.createElement('div');
    viewport.className = 'gap-virt-sentinel';
    container.appendChild(viewport);

    // 把所有卡片用 transform 绝对定位
    const layout = []; // {card, top}
    let y = 0;
    cards.forEach((card) => {
      card.style.position = 'absolute';
      card.style.left = '0';
      card.style.right = '0';
      card.style.top = y + 'px';
      const h = card.getBoundingClientRect().height || 140;
      layout.push({ card, top: y, h });
      y += h + 12; // gap:12px
    });
    viewport.style.height = y + 'px';

    function render() {
      const rect = container.getBoundingClientRect();
      const top = rect.top + window.scrollY;
      const viewStart = window.scrollY - top - VIEWPORT * OVERSCAN;
      const viewEnd = window.scrollY - top + window.innerHeight + VIEWPORT * OVERSCAN;
      for (const item of layout) {
        if (item.top + item.h < viewStart || item.top > viewEnd) {
          item.card.style.visibility = 'hidden';
        } else {
          item.card.style.visibility = '';
        }
      }
    }
    const onScroll = Utils.debounce(render, 30);
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    render();
  }

  return { activate, bindCollapsibles };
})();

/* ==========================================================================
 * 5. s-axis — 五线横向 S 轴布局
 * ========================================================================== */
const SAxis = (() => {
  const SNAKE_THRESHOLD = 5;

  function stripVerticalChrome(node) {
    node.querySelectorAll('.node-line, .node-dot').forEach((el) => el.remove());
  }

  function ensureCardToggle(node) {
    const content = node.querySelector('.node-content');
    if (!content || content.querySelector('.node-gap-toggle')) return;
    const hasDetail = content.querySelector(
      '.node-ok:not(.node-gap--collapsible), .node-gap:not(.node-gap--collapsible), .node-gap--collapsible'
    );
    if (!hasDetail) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'node-gap-toggle';
    btn.textContent = '展开详情';
    content.appendChild(btn);
  }

  function collectNodes(body) {
    return [...body.children].filter((el) => el.classList.contains('flow-node'));
  }

  function makeGridArrow(symbol, col, row, extraClass) {
    const el = document.createElement('div');
    el.className = 's-axis-grid-arrow' + (extraClass ? ' ' + extraClass : '');
    el.textContent = symbol;
    el.setAttribute('aria-hidden', 'true');
    el.style.gridColumn = String(col);
    el.style.gridRow = String(row);
    return el;
  }

  function buildGridTemplate(colCount) {
    const parts = [];
    for (let i = 0; i < colCount; i++) {
      parts.push('minmax(0, 1fr)');
      if (i < colCount - 1) parts.push('var(--s-axis-arrow-w, 22px)');
    }
    return parts.join(' ');
  }

  function createGrid(body, colCount, singleRow) {
    const arrowW = 22;
    const template = buildGridTemplate(colCount);
    body.style.setProperty('--s-axis-cols', String(colCount));
    body.style.setProperty('--s-axis-grid-cols', String(Math.max(colCount * 2 - 1, 1)));
    body.style.setProperty('--s-axis-grid-template', template);
    body.style.setProperty('--s-axis-arrow-w', arrowW + 'px');
    body.style.removeProperty('--s-axis-grid-min-w');
    body.style.removeProperty('--s-axis-card-w');
    const grid = document.createElement('div');
    grid.className = 's-axis-snake-grid' + (singleRow ? ' s-axis-snake-grid--single' : '');
    grid.style.gridTemplateColumns = template;
    grid.style.width = '100%';
    grid.style.minWidth = '0';
    return grid;
  }

  function drawFlowPath(grid, splitAt) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 's-axis-flow-lines');
    svg.setAttribute('aria-hidden', 'true');
    grid.appendChild(svg);

    const render = () => {
      try {
        const ordered = [...grid.querySelectorAll('.flow-node')].sort(
          (a, b) => Number(a.dataset.sAxisIdx) - Number(b.dataset.sAxisIdx)
        );
        if (ordered.length < 2) return;

        const box = grid.getBoundingClientRect();
        if (box.width < 1 || box.height < 1) return;

        svg.setAttribute('viewBox', '0 0 ' + box.width + ' ' + box.height);
        svg.style.width = box.width + 'px';
        svg.style.height = box.height + 'px';
        svg.innerHTML = '';

        const center = (el) => {
          const r = el.getBoundingClientRect();
          return {
            x: r.left - box.left + r.width / 2,
            y: r.top - box.top + r.height / 2,
            bottom: r.bottom - box.top,
            top: r.top - box.top,
          };
        };

        const pts = ordered.map(center);
        let d = 'M ' + pts[0].x + ' ' + pts[0].y;

        for (let i = 0; i < pts.length - 1; i++) {
          const a = pts[i];
          const b = pts[i + 1];
          if (splitAt > 0 && i === splitAt - 1) {
            const midY = (a.bottom + b.top) / 2;
            d += ' L ' + a.x + ' ' + midY + ' L ' + b.x + ' ' + midY + ' L ' + b.x + ' ' + b.y;
          } else {
            d += ' L ' + b.x + ' ' + b.y;
          }
        }

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', d);
        path.setAttribute('class', 's-axis-flow-path');
        svg.appendChild(path);

        for (let i = 0; i < pts.length - 1; i++) {
          if (splitAt > 0 && i === splitAt - 1) continue;
          const a = pts[i];
          const b = pts[i + 1];
          const mx = (a.x + b.x) / 2;
          const my = (a.y + b.y) / 2;
          const angle = Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI;
          const head = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          head.setAttribute('class', 's-axis-flow-head');
          head.setAttribute('points', '0,-4 8,0 0,4');
          head.setAttribute('transform', 'translate(' + mx + ',' + my + ') rotate(' + angle + ')');
          svg.appendChild(head);
        }

        if (splitAt > 0 && pts[splitAt - 1] && pts[splitAt]) {
          const turn = pts[splitAt - 1];
          const next = pts[splitAt];
          const midY = (turn.bottom + next.top) / 2;
          const downHead = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          downHead.setAttribute('class', 's-axis-flow-head');
          downHead.setAttribute('points', '0,-4 8,0 0,4');
          downHead.setAttribute('transform', 'translate(' + turn.x + ',' + midY + ') rotate(90)');
          svg.appendChild(downHead);

          const leftHead = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          leftHead.setAttribute('class', 's-axis-flow-head');
          leftHead.setAttribute('points', '0,-4 8,0 0,4');
          leftHead.setAttribute('transform', 'translate(' + next.x + ',' + midY + ') rotate(180)');
          svg.appendChild(leftHead);
        }
      } catch (err) {
        console.warn('[SAxis] flow path render skipped:', err);
      }
    };

    requestAnimationFrame(render);
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(() => requestAnimationFrame(render));
      ro.observe(grid);
    }
  }

  function appendRowNodes(grid, nodes, row, startIdx, dir, colBasis) {
    const cols = colBasis || nodes.length;
    nodes.forEach((node, i) => {
      stripVerticalChrome(node);
      ensureCardToggle(node);
      node.dataset.sAxisIdx = String(startIdx + i + 1);
      if (dir === 'ltr') {
        node.style.gridColumn = String(i * 2 + 1);
        grid.appendChild(node);
        if (i < nodes.length - 1) {
          grid.appendChild(makeGridArrow('→', i * 2 + 2, row, 's-axis-grid-arrow--h'));
        }
      } else {
        node.style.gridColumn = String((cols - 1 - i) * 2 + 1);
        grid.appendChild(node);
        if (i < nodes.length - 1) {
          grid.appendChild(makeGridArrow('←', (cols - 2 - i) * 2 + 2, row, 's-axis-grid-arrow--h'));
        }
      }
      node.style.gridRow = String(row);
    });
  }

  function layoutFlatGrid(body, nodes) {
    const grid = createGrid(body, nodes.length, true);
    appendRowNodes(grid, nodes, 1, 0, 'ltr');
    body.appendChild(grid);
    drawFlowPath(grid, 0);
  }

  function layoutSnakeGrid(body, row1, row2) {
    const colCount = Math.max(row1.length, row2.length);
    const grid = createGrid(body, colCount, false);
    appendRowNodes(grid, row1, 1, 0, 'ltr');
    grid.appendChild(makeGridArrow('↓', colCount * 2 - 1, 2, 's-axis-grid-arrow--bridge'));
    appendRowNodes(grid, row2, 3, row1.length, 'rtl', colCount);
    body.appendChild(grid);
    drawFlowPath(grid, row1.length);
  }

  function layoutBody(body) {
    if (body.dataset.sAxisDone) return;
    const nodes = collectNodes(body);
    if (!nodes.length) return;

    try {
      body.dataset.sAxisDone = '1';
      [...body.children].forEach((el) => {
        if (el.classList.contains('node-connector')) el.remove();
      });
      body.textContent = '';

      if (nodes.length >= SNAKE_THRESHOLD) {
        body.classList.add('s-axis--snake');
        const split = Math.ceil(nodes.length / 2);
        layoutSnakeGrid(body, nodes.slice(0, split), nodes.slice(split));
      } else {
        body.classList.add('s-axis--flat');
        layoutFlatGrid(body, nodes);
      }
    } catch (err) {
      console.error('[SAxis] layout failed:', err);
      delete body.dataset.sAxisDone;
    }
  }

  function bindExpand(root) {
    const scope = root || document;
    scope.querySelectorAll('.loop-body.s-axis .flow-node').forEach((node) => {
      if (node.dataset.sAxisBound) return;
      node.dataset.sAxisBound = '1';
      node.addEventListener('click', (e) => {
        if (e.target.closest('.node-gap-toggle')) return;
        node.classList.toggle('is-open');
      });
    });
  }

  function activate() {
    document.querySelectorAll('.loop-body.s-axis').forEach(layoutBody);
    bindExpand();
  }

  return { activate, bindExpand, layoutBody };
})();

/* ==========================================================================
 * 5b. line-view — 单线全量查看（#line/{id} + 独立页）
 * ========================================================================== */
const LineView = (() => {
  const LINE_IDS = new Set(['ops_acquisition', 'ops_partner', 'prod_web', 'prod_mod', 'prod_software', 'shared_retention']);
  const BASE_TITLE = document.title;
  let shell = null;

  function lineUrl(lineId) {
    return 'XCAGI-Five-Line.html?line=' + encodeURIComponent(lineId);
  }

  function ensureShell() {
    if (shell) return shell;
    shell = document.createElement('div');
    shell.id = 'line-fullview';
    shell.className = 'line-fullview';
    shell.hidden = true;
    shell.setAttribute('role', 'dialog');
    shell.setAttribute('aria-modal', 'true');
    shell.innerHTML =
      '<header class="line-fullview__bar">' +
        '<button type="button" class="line-fullview__back" id="line-fullview-back">← 返回五线总览</button>' +
        '<div class="line-fullview__meta">' +
          '<h1 class="line-fullview__title" id="line-fullview-title"></h1>' +
          '<p class="line-fullview__legacy" id="line-fullview-legacy"></p>' +
        '</div>' +
        '<div class="line-fullview__tools">' +
          '<button type="button" class="line-fullview__toggle" id="line-fullview-toggle">收起全部详情</button>' +
          '<span class="line-fullview__rate" id="line-fullview-rate"></span>' +
        '</div>' +
      '</header>' +
      '<div class="line-fullview__body"><div class="line-fullview__stage" id="line-fullview-stage"></div></div>';
    document.body.appendChild(shell);

    shell.querySelector('#line-fullview-back').addEventListener('click', close);
    shell.querySelector('#line-fullview-toggle').addEventListener('click', toggleExpandAll);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !shell.hidden) close();
    });
    return shell;
  }

  function injectActions() {
    document.querySelectorAll('.loop--five-line').forEach((loop) => {
      if (loop.querySelector('.loop-fullview-actions')) return;
      const lineId = loop.dataset.fiveLine;
      if (!lineId) return;
      const actions = document.createElement('div');
      actions.className = 'loop-fullview-actions';
      actions.innerHTML =
        '<button type="button" class="loop-fullview-btn" data-line-open="' + lineId + '">全量查看</button>' +
        '<a class="loop-fullview-link" href="' + lineUrl(lineId) + '" target="_blank" rel="noopener">新标签 ↗</a>';
      const header = loop.querySelector('.loop-header');
      const progress = loop.querySelector('.loop-progress');
      if (header && progress) header.insertBefore(actions, progress);
      else if (header) header.appendChild(actions);
    });
  }

  function setExpanded(root, expanded) {
    root.querySelectorAll('.flow-node').forEach((n) => n.classList.toggle('is-open', expanded));
    root.querySelectorAll('.node-gap--collapsible').forEach((n) => n.classList.toggle('is-open', expanded));
    const btn = document.getElementById('line-fullview-toggle');
    if (btn) btn.textContent = expanded ? '收起全部详情' : '展开全部详情';
    if (shell) shell.dataset.expandedAll = expanded ? '1' : '0';
  }

  function toggleExpandAll() {
    if (!shell) return;
    const stage = shell.querySelector('#line-fullview-stage');
    const next = shell.dataset.expandedAll !== '1';
    setExpanded(stage, next);
  }

  function open(lineId, opts) {
    if (!LINE_IDS.has(lineId)) return;
    const source = document.querySelector('.loop--five-line[data-five-line="' + lineId + '"]');
    if (!source) return;

    ensureShell();
    Router.show('loops', { skipScroll: true });

    const titleEl = source.querySelector('.loop-title');
    const subtitleEl = source.querySelector('.loop-subtitle');
    const legacyEl = source.querySelector('.loop-map-legacy');
    const rateEl = source.querySelector('.loop-progress-num');

    document.getElementById('line-fullview-title').textContent =
      (titleEl ? titleEl.textContent : lineId) + (subtitleEl ? ' · ' + subtitleEl.textContent : '');
    const legacyNode = document.getElementById('line-fullview-legacy');
    legacyNode.innerHTML = legacyEl ? legacyEl.innerHTML : '';
    document.getElementById('line-fullview-rate').textContent = rateEl ? rateEl.textContent + ' 自动化率' : '';

    const stage = document.getElementById('line-fullview-stage');
    stage.innerHTML = '';
    const clone = source.cloneNode(true);
    clone.classList.add('loop--fullview');
    clone.querySelectorAll('.loop-fullview-actions').forEach((el) => el.remove());
    stage.appendChild(clone);

    setExpanded(stage, true);
    SAxis.bindExpand(clone);

    shell.hidden = false;
    document.body.classList.add('line-fullview-open');
    document.title = (titleEl ? titleEl.textContent : lineId) + ' · 全量流程 · XCAGI';

    if (!opts || !opts.skipHash) {
      const target = '#line/' + lineId;
      if (location.hash !== target) history.pushState({ lineView: lineId }, '', target);
    }

    shell.querySelector('.line-fullview__body').scrollTop = 0;
    shell.querySelector('#line-fullview-back').focus();
  }

  function close(opts) {
    if (!shell || shell.hidden) return;
    shell.hidden = true;
    document.body.classList.remove('line-fullview-open');
    document.getElementById('line-fullview-stage').innerHTML = '';
    document.title = BASE_TITLE;
    if (!opts || !opts.skipHash) {
      const target = '#s-loops';
      if (location.hash !== target) history.pushState(null, '', target);
    }
  }

  function syncFromHash() {
    const hash = location.hash.replace(/^#/, '');
    const m = /^line\/([a-z_]+)$/.exec(hash);
    if (m && LINE_IDS.has(m[1])) {
      open(m[1], { skipHash: true });
      return;
    }
    if (!shell || shell.hidden) return;
    close({ skipHash: true });
  }

  function bind() {
    injectActions();
    ensureShell();
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-line-open]');
      if (btn) {
        e.preventDefault();
        open(btn.getAttribute('data-line-open'));
      }
    });
    window.addEventListener('hashchange', syncFromHash);
    window.addEventListener('popstate', syncFromHash);
    syncFromHash();
  }

  return { bind, open, close, lineUrl, LINE_IDS };
})();

/* ==========================================================================
 * 5b. LineCoverage — 六线目录归属覆盖率
 * ========================================================================== */
const LineCoverage = (() => {
  const SHORT = {
    ops_acquisition: 'O-A',
    ops_partner: 'O-B',
    prod_web: 'P-W',
    prod_mod: 'P-M',
    prod_software: 'P-S',
    shared_retention: 'S-R',
    meta: 'Meta',
  };
  const CLS = {
    ops_acquisition: 'tag-oa',
    ops_partner: 'tag-ob',
    prod_web: 'tag-pw',
    prod_mod: 'tag-pm',
    prod_software: 'tag-ps',
    shared_retention: 'tag-sr',
    meta: 'tag-meta',
  };
  const ORDER = ['prod_web', 'prod_software', 'shared_retention', 'ops_acquisition', 'prod_mod', 'meta', 'ops_partner'];

  let cached = null;

  async function loadStepMap() {
    return dashFetchJson('six_line_employee_map.json?v=20260603u', { cache: 'no-store' });
  }

  function stepCoveragePct(mapDoc) {
    if (!mapDoc || !mapDoc.lines) return null;
    let total = 0;
    let covered = 0;
    for (const block of Object.values(mapDoc.lines)) {
      const steps = block.steps || {};
      for (const step of Object.values(steps)) {
        total += 1;
        if (step.primary && step.primary.length) covered += 1;
      }
    }
    return total ? (covered / total) * 100 : null;
  }

  function staffCodesHtml(ids) {
    return (ids || []).map((id) => '<code>' + Utils.escapeHtml(id) + '</code>').join(' · ');
  }

  function buildStaffLineHtml(lineLabel, step) {
    const primary = step.primary || [];
    const support = step.support || [];
    let html = Utils.escapeHtml(lineLabel || '') + ' · 主责 ' + staffCodesHtml(primary);
    if (support.length) html += ' · 协作 ' + staffCodesHtml(support);
    return html;
  }

  function syncFlowNodeStaffFromMap(mapDoc) {
    if (!mapDoc || !mapDoc.lines) return 0;
    let synced = 0;
    document.querySelectorAll('.flow-node[data-five-line]').forEach((node) => {
      const lineId = node.getAttribute('data-five-line');
      const stepId = node.getAttribute('data-ops-step') || node.getAttribute('data-prod-step');
      if (!lineId || !stepId) return;
      const block = mapDoc.lines[lineId];
      const step = block && block.steps ? block.steps[stepId] : null;
      if (!step) return;
      const el = node.querySelector('.node-dept-staff');
      if (!el) return;
      el.innerHTML = buildStaffLineHtml(block.label || lineId, step);
      synced += 1;
    });
    return synced;
  }

  async function loadStepEmployeeAudit() {
    return dashFetchJson('.cache/xcmax/xcmax-step-employee-coverage.json?v=20260603w', { cache: 'no-store' });
  }

  function renderStepEmployeePanel(audit, mapDoc) {
    const panel = document.getElementById('step-employee-panel');
    if (!panel) return;
    panel.hidden = false;

    const bindingEl = document.getElementById('step-employee-binding');
    const tableEl = document.getElementById('step-employee-table');
    const footEl = document.getElementById('step-employee-foot');

    if (bindingEl && audit) {
      bindingEl.className = 'path-employee-binding step-employee-binding ' +
        (audit.full_step_coverage && audit.full_roster_step_binding !== false ? 'is-ok' : 'is-warn');
      const rosterGap = audit.roster_not_in_steps && audit.roster_not_in_steps.length;
      const title = audit.full_step_coverage
        ? '流程步骤员工覆盖 ✅（' + audit.step_count + ' 步均有主责）'
        : '流程步骤员工覆盖 ⚠';
      bindingEl.innerHTML =
        '<div class="pe-binding-title">' + Utils.escapeHtml(title) + '</div>' +
        '<div class="pe-binding-grid">' +
        '<div class="pe-binding-stat"><strong>' + fmtPct(audit.step_coverage_pct) + '%</strong>步骤有主责</div>' +
        '<div class="pe-binding-stat"><strong>' + (audit.step_count || 0) + '</strong>流程步骤</div>' +
        '<div class="pe-binding-stat"><strong>' + (audit.unique_primary_count || 0) + '</strong>主责编制</div>' +
        '<div class="pe-binding-stat"><strong>' + fmtPct(audit.roster_step_coverage_pct) + '%</strong>编制落步</div>' +
        '<div class="pe-binding-stat"><strong>' + (audit.workflow_mod_count || 0) + '</strong>流程 Mod</div>' +
        '</div>' +
        '<div class="pe-binding-note">每个流程节点下方 <code>node-dept-staff</code> 由 <code>six_line_employee_map.json</code> 加载时同步；编制 52 人 + 6 个 workflow Mod 协作岗。</div>' +
        (rosterGap
          ? '<div class="pe-binding-gaps">编制未出现在任一步骤（可接受：质检/访谈岗）：' +
            Utils.escapeHtml(audit.roster_not_in_steps.join('、')) + '</div>'
          : '') +
        (audit.unknown_employee_refs && audit.unknown_employee_refs.length
          ? '<div class="pe-binding-gaps">步骤引用未知编制：' +
            Utils.escapeHtml(audit.unknown_employee_refs.join('、')) + '</div>'
          : '');
    }

    if (tableEl) {
      tableEl.replaceChildren();
      const head = document.createElement('div');
      head.className = 'se-table-row se-table-head';
      head.innerHTML = '<span>步骤</span><span>线 / 名称</span><span>主责</span><span>协作</span>';
      tableEl.appendChild(head);
      const rows = (audit && audit.steps) ? audit.steps.slice() : [];
      if (!rows.length && mapDoc && mapDoc.lines) {
        for (const [lineId, block] of Object.entries(mapDoc.lines)) {
          for (const [stepId, step] of Object.entries(block.steps || {})) {
            rows.push({
              line_id: lineId,
              line_label: block.label || lineId,
              step_id: stepId,
              step_name: step.name || stepId,
              primary: step.primary || [],
              support: step.support || [],
            });
          }
        }
      }
      for (const row of rows) {
        const tr = document.createElement('div');
        tr.className = 'se-table-row';
        tr.innerHTML =
          '<span class="se-step"><code>' + Utils.escapeHtml(row.step_id) + '</code></span>' +
          '<span>' + Utils.escapeHtml((SHORT[row.line_id] || row.line_label || row.line_id) + ' · ' + (row.step_name || '')) + '</span>' +
          '<span class="se-staff">' + staffCodesHtml(row.primary) + '</span>' +
          '<span class="se-staff">' + (row.support && row.support.length ? staffCodesHtml(row.support) : '—') + '</span>';
        tableEl.appendChild(tr);
      }
    }

    if (footEl && mapDoc) {
      footEl.textContent =
        '数据版本 ' + (mapDoc.version || '—') + ' · 已同步 ' +
        syncFlowNodeStaffFromMap(mapDoc) + ' 个流程节点主责行';
    }
  }

  function renderStepHero(mapDoc, lineData, stepAudit) {
    const pct = stepAudit && stepAudit.step_coverage_pct != null
      ? stepAudit.step_coverage_pct
      : stepCoveragePct(mapDoc);
    const el = document.getElementById('hero-step-coverage-pct');
    const subEl = document.getElementById('hero-step-coverage-sub');
    if (el && pct != null) el.textContent = fmtPct(pct) + '%';
    if (subEl && stepAudit) {
      subEl.textContent =
        stepAudit.steps_with_primary + ' / ' + stepAudit.step_count + ' 流程步骤有主责 · ' +
        stepAudit.roster_in_steps_count + ' / ' + stepAudit.roster_count + ' 编制落步 · ' +
        (stepAudit.workflow_mod_count || 0) + ' 流程 Mod';
    } else if (subEl && mapDoc) {
      subEl.textContent = '步骤员工映射见 six_line_employee_map.json';
    }
    if (lineData) renderHero(lineData);
  }

  async function loadPytestCoverage() {
    const paths = [
      'xcmax-pytest-coverage.json',
      '.cache/xcmax/xcmax-pytest-coverage.json',
      'FHD/metrics/coverage-dual-summary.json',
    ];
    for (const path of paths) {
      const data = await dashFetchJson(path + '?v=20260604d', { cache: 'no-store' });
      if (data && data.full_app) return data;
    }
    return null;
  }

  function renderPytestCoverageHero(data) {
    if (!data || !data.full_app) return;
    const full = data.full_app;
    const core = data.measured_core_c1 || {};
    const pctEl = document.getElementById('hero-pytest-full-pct');
    const subEl = document.getElementById('hero-pytest-coverage-sub');
    if (pctEl) pctEl.textContent = fmtPct(full.pct) + '%';
    if (subEl) {
      subEl.textContent =
        (full.covered || 0).toLocaleString() + ' / ' + (full.statements || 0).toLocaleString() +
        ' 行 · full app · measured core C1 ' + fmtPct(core.pct) + '%（' +
        (core.statements || 0).toLocaleString() + ' 行）· pass stub ' +
        (data.pass_stub_files != null ? data.pass_stub_files : '—') + ' 文件';
    }
  }

  async function load() {
    if (cached) return cached;
    cached = await dashFetchJson('.cache/xcmax/xcmax-line-coverage.json?v=20260603u', { cache: 'no-store' });
    return cached;
  }

  function fmtPct(n) {
    return (typeof n === 'number' ? n : parseFloat(n) || 0).toFixed(1);
  }

  function renderPathEmployeeHero(pe) {
    if (!pe) return;
    const zoneEl = document.getElementById('hero-path-zone-coverage-pct');
    const fileEl = document.getElementById('hero-path-file-coverage-pct');
    const subEl = document.getElementById('hero-path-coverage-sub');
    if (zoneEl) zoneEl.textContent = fmtPct(pe.zone_coverage_pct) + '%';
    if (fileEl) fileEl.textContent = fmtPct(pe.file_coverage_pct) + '%';
    if (subEl) {
      subEl.textContent =
        pe.staffed_zones + ' / ' + pe.zone_count + ' 分区有主责 · ' +
        (pe.gap_zones || 0) + ' 缺口';
    }
  }

  function renderEmployeeBindingPanel(binding) {
    const el = document.getElementById('pe-employee-binding');
    if (!el || !binding) return;
    el.hidden = false;
    el.classList.remove('is-ok', 'is-warn');
    el.classList.add(binding.full_coverage ? 'is-ok' : 'is-warn');

    const pct = fmtPct(binding.full_coverage_pct);
    const pathPct = fmtPct(binding.path_expected_coverage_pct);
    const title = binding.full_coverage
      ? '员工系统全量绑定 ✅（编制 ' + binding.roster_count + ' 人）'
      : '员工系统绑定未完成 ⚠（' + binding.fully_bound_count + ' / ' + binding.roster_count + '）';

    let html =
      '<div class="pe-binding-title">' + Utils.escapeHtml(title) + '</div>' +
      '<div class="pe-binding-grid">' +
      '<div class="pe-binding-stat"><strong>' + pct + '%</strong>三元绑定</div>' +
      '<div class="pe-binding-stat"><strong>' + (binding.path_rule_primary_count || 0) + '</strong>路径主责</div>' +
      '<div class="pe-binding-stat"><strong>' + (binding.workspace_pack_count || 0) + '</strong>yuangon/mods</div>' +
      '<div class="pe-binding-stat"><strong>' + pathPct + '%</strong>路径规则覆盖</div>' +
      '<div class="pe-binding-stat"><strong>' + (binding.craft_exempt_count || 0) + '</strong>Craft 豁免</div>' +
      '<div class="pe-binding-stat"><strong>' + (binding.partner_exempt_count || 0) + '</strong>O-B 豁免</div>' +
      '</div>' +
      '<div class="pe-binding-note">绑定逻辑：编制员工须满足「xcmax_path_employee_map 主责」或「yuangon/**/employee.yaml + FHD/mods/_employees/」工作区；Craft 13 步与 O-B 伙伴部按 duty_roster 豁免路径规则。</div>';

    if (binding.path_rule_gaps && binding.path_rule_gaps.length) {
      html += '<div class="pe-binding-gaps">无路径主责（靠工作区绑定）：' +
        Utils.escapeHtml(binding.path_rule_gaps.join('、')) + '</div>';
    }
    if (binding.unbound && binding.unbound.length) {
      html += '<div class="pe-binding-gaps">未绑定：' + Utils.escapeHtml(binding.unbound.join('、')) + '</div>';
    }
    if (binding.path_primary_not_in_roster && binding.path_primary_not_in_roster.length) {
      html += '<div class="pe-binding-gaps">路径规则引用未知编制：' +
        Utils.escapeHtml(binding.path_primary_not_in_roster.join('、')) + '</div>';
    }
    el.innerHTML = html;
  }

  function renderPathEmployeePanel(pe) {
    if (!pe) return;
    renderPathEmployeeHero(pe);
    const panel = document.getElementById('path-employee-panel');
    if (!panel) return;
    panel.hidden = false;

    const table = document.getElementById('pe-zone-table');
    const gapsEl = document.getElementById('pe-gaps-list');
    const dutyEl = document.getElementById('pe-duty-foot');

    if (table) {
      table.replaceChildren();
      const head = document.createElement('div');
      head.className = 'pe-table-row pe-table-head';
      head.innerHTML = '<span>路径</span><span>部门</span><span>主责员工</span><span>文件</span>';
      table.appendChild(head);
      const sorted = (pe.zones || []).slice().sort((a, b) => (b.files || 0) - (a.files || 0));
      for (const row of sorted.slice(0, 40)) {
        const tr = document.createElement('div');
        tr.className = 'pe-table-row' + (!(row.primary && row.primary.length) ? ' is-gap' : '');
        const dept = row.department || '—';
        const staff = (row.primary && row.primary.length) ? row.primary.join(', ') : '—';
        tr.innerHTML =
          '<span class="pe-path">' + Utils.escapeHtml(row.path) + '</span>' +
          '<span class="pe-dept">' + Utils.escapeHtml(LineCoverage.SHORT[dept] || dept) + '</span>' +
          '<span class="pe-staff">' + Utils.escapeHtml(staff) + '</span>' +
          '<span class="pe-files">' + (row.files || 0).toLocaleString() + '</span>';
        table.appendChild(tr);
      }
    }

    if (gapsEl) {
      const gaps = pe.gaps || [];
      if (!gaps.length) {
        gapsEl.textContent = '二级分区全部有主责员工规则';
      } else {
        gapsEl.textContent = '缺口分区：' + gaps.map((g) => g.path).join('、');
      }
    }

    if (dutyEl && pe.duty_gaps) {
      const dg = pe.duty_gaps;
      const parts = [
        'yuangon 编制 ' + dg.planned_yuangon_count + ' · YAML ' + dg.yaml_on_disk_count +
          (dg.yaml_aligned ? ' · 对齐 ✅' : ' · 未对齐 ⚠'),
      ];
      if (dg.employee_binding && dg.employee_binding.full_coverage) {
        parts.push('员工三元绑定 ' + dg.employee_binding.fully_bound_count + '/' + dg.employee_binding.roster_count + ' ✅');
      } else if (dg.employee_binding) {
        parts.push('员工三元绑定 ' + dg.employee_binding.fully_bound_count + '/' + dg.employee_binding.roster_count + ' ⚠');
      }
      if (dg.workflow_mod_count) {
        parts.push('工作流 Mod 员工 ' + dg.workflow_mod_count + '（O-A 单据/CRM 域）');
      }
      if (dg.ob_reserved) parts.push('O-B 预留零编制');
      dutyEl.textContent = parts.join(' · ');
    }

    if (pe.duty_gaps && pe.duty_gaps.employee_binding) {
      renderEmployeeBindingPanel(pe.duty_gaps.employee_binding);
    }
  }

  async function loadPathEmployee() {
    return dashFetchJson('.cache/xcmax/xcmax-path-employee-coverage.json?v=20260603v', { cache: 'no-store' });
  }

  function renderHero(data) {
    if (!data) return;
    const pctEl = document.getElementById('hero-line-coverage-pct');
    const subEl = document.getElementById('hero-line-coverage-sub');
    if (pctEl) pctEl.textContent = fmtPct(data.coverage_pct) + '%';
    if (subEl) {
      subEl.textContent = data.mapped_files.toLocaleString() + ' / ' + data.scanned_files.toLocaleString() + ' 文件已归属';
    }
  }

  function barRow(label, pct, cls, files) {
    const row = document.createElement('div');
    row.className = 'lc-bar-row';
    row.innerHTML =
      '<span class="lc-bar-label ' + cls + '">' + Utils.escapeHtml(label) + '</span>' +
      '<div class="lc-bar-track"><div class="lc-bar-fill ' + cls + '" style="width:' + Math.min(100, pct) + '%"></div></div>' +
      '<span class="lc-bar-pct">' + fmtPct(pct) + '%</span>' +
      '<span class="lc-bar-files">' + (files || 0).toLocaleString() + '</span>';
    return row;
  }

  function renderPanel(data) {
    if (!data) return;
    const panel = document.getElementById('line-coverage-panel');
    if (!panel) return;
    panel.hidden = false;

    const pctEl = document.getElementById('lc-pct');
    const ratioEl = document.getElementById('lc-ratio');
    const primaryEl = document.getElementById('lc-bars-primary');
    const overlapEl = document.getElementById('lc-bars-overlap');
    const footEl = document.getElementById('lc-foot');

    if (pctEl) pctEl.textContent = fmtPct(data.coverage_pct);
    if (ratioEl) {
      ratioEl.textContent = data.mapped_files.toLocaleString() + ' / ' + data.scanned_files.toLocaleString();
    }

    if (primaryEl) {
      primaryEl.replaceChildren();
      const title = document.createElement('div');
      title.className = 'lc-section-title';
      title.textContent = '主归属分区（互斥 · 合计 100%）';
      primaryEl.appendChild(title);
      const sorted = ORDER
        .map((id) => [id, data.by_primary[id]])
        .filter(([, row]) => row && row.files > 0)
        .sort((a, b) => b[1].pct_of_scanned - a[1].pct_of_scanned);
      for (const [id, row] of sorted) {
        primaryEl.appendChild(barRow(row.label, row.pct_of_scanned, CLS[id] || '', row.files));
      }
    }

    if (overlapEl) {
      overlapEl.replaceChildren();
      const title = document.createElement('div');
      title.className = 'lc-section-title';
      title.textContent = '逻辑归属（含重叠 · 可大于 100%）';
      overlapEl.appendChild(title);
      const sorted = ORDER
        .map((id) => [id, data.by_line[id]])
        .filter(([, row]) => row && row.files > 0)
        .sort((a, b) => b[1].pct_of_scanned - a[1].pct_of_scanned);
      for (const [id, row] of sorted) {
        overlapEl.appendChild(barRow(row.label, row.pct_of_scanned, CLS[id] || '', row.files));
      }
    }

    if (footEl) {
      const parts = [];
      if (data.unmapped && data.unmapped.length) {
        parts.push('未归属：' + data.unmapped.map((u) => u.path).join('、'));
      } else {
        parts.push('扫描范围内全部顶层路径已配置归属规则');
      }
      if (data.excluded_s_r && data.excluded_s_r.length) {
        parts.push('扫描排除项逻辑归 S-R：' + data.excluded_s_r.map((e) => e.path).join(' '));
      }
      footEl.textContent = parts.join(' · ');
    }

    renderHero(data);
    if (data.path_employee) renderPathEmployeePanel(data.path_employee);
  }

  async function activate() {
    const data = await load();
    const pytestCov = await loadPytestCoverage();
    renderPytestCoverageHero(pytestCov);
    const mapDoc = await loadStepMap();
    const stepAudit = await loadStepEmployeeAudit();
    const pathPe = (data && data.path_employee) ? data.path_employee : await loadPathEmployee();
    if (data) renderPanel(data);
    if (pathPe) renderPathEmployeePanel(pathPe);
    if (mapDoc) {
      syncFlowNodeStaffFromMap(mapDoc);
      renderStepEmployeePanel(stepAudit || (data && data.step_employee), mapDoc);
    }
    if (mapDoc || stepAudit) renderStepHero(mapDoc, data, stepAudit || (data && data.step_employee));
    else if (data) renderHero(data);
  }

  return {
    load,
    loadPytestCoverage,
    activate,
    renderPanel,
    renderPathEmployeePanel,
    renderStepEmployeePanel,
    renderPytestCoverageHero,
    syncFlowNodeStaffFromMap,
    renderHero,
    SHORT,
    CLS,
  };
})();

/* ==========================================================================
 * 5c. releaseTrain — 四段 SSOT live
 * ========================================================================== */
const ReleaseTrain = (() => {
  const STATIC_PATHS = [
    '/xcmax-dashboard/FHD/config/release_train.json',
    'FHD/config/release_train.json',
  ];

  function enrichSnapshot(raw) {
    if (!raw || typeof raw !== 'object') return null;
    if (raw.is_installer_day !== undefined && raw.is_major_day !== undefined) return raw;
    const cur = String(raw.current || '1.0.0.0');
    const dayIndex = Number(raw.day_index || 0);
    const parts = cur.split('.').map((p) => parseInt(p, 10));
    const d = Number.isFinite(parts[3]) ? parts[3] : 0;
    const c = Number.isFinite(parts[2]) ? parts[2] : 0;
    const gen = Number.isFinite(raw.decennial_generation) ? raw.decennial_generation : c + 1;
    const genLabel = raw.decennial_generation_label || ('G' + gen);
    const mAnalog = raw.marketing_analog || ('v' + gen);
    const nextParts = cur.split('.').map((p) => parseInt(p, 10));
    let nd = (Number.isFinite(nextParts[3]) ? nextParts[3] : 0) + 1;
    let nc = Number.isFinite(nextParts[2]) ? nextParts[2] : 0;
    if (nd >= 10) { nd = 0; nc += 1; }
    const nextVer = [nextParts[0] || 1, nextParts[1] || 0, nc, nd].join('.');
    const nextDay = dayIndex + 1;
    let nextKind = 'daily';
    if (nextDay > 0 && nextDay % 100 === 0) nextKind = 'major';
    else if (nd === 0 && nextDay > 0) nextKind = 'installer';
    return {
      ...raw,
      is_installer_day: d === 0 && dayIndex > 0,
      is_major_day: dayIndex > 0 && dayIndex % 100 === 0,
      next_kind_hint: nextKind,
      decennial_generation: gen,
      decennial_generation_label: genLabel,
      marketing_analog: mAnalog,
      next_decennial_anchor: raw.next_decennial_anchor || [parts[0] || 1, parts[1] || 0, c + 1, 0].join('.'),
      _source: raw._source || 'static',
    };
  }

  async function fetchStaticJson() {
    for (const path of STATIC_PATHS) {
      const raw = await dashFetchJson(path + '?v=20260604c', { cache: 'no-store' });
      if (raw && raw.current) return enrichSnapshot({ ...raw, _source: path });
    }
    return null;
  }

  async function fetchSnapshot() {
    try {
      const resp = await fetch(
        (window.XCAGIApi && window.XCAGIApi.url('/api/xcmax/release-train')) || '/api/xcmax/release-train',
        { cache: 'no-store' }
      );
      if (resp.ok) {
        const ct = (resp.headers.get('content-type') || '').toLowerCase();
        if (!ct.includes('text/html')) {
          const json = await resp.json();
          const data = json && json.data ? json.data : json;
          if (data && data.current) return enrichSnapshot({ ...data, _source: 'api' });
        }
      }
    } catch (_) { /* fallback static */ }
    return fetchStaticJson();
  }

  function apply(data) {
    if (!data) return;
    const cur = String(data.current || '—');
    const dayIdx = data.day_index != null ? data.day_index : '—';
    const kind = String(data.release_kind || data.next_kind_hint || 'daily');
    const hero = document.getElementById('hero-release-train');
    if (hero) hero.textContent = cur;
    const heroGen = document.getElementById('hero-release-gen');
    if (heroGen) {
      const gl = data.decennial_generation_label || ('G' + (data.decennial_generation || '—'));
      const ma = data.marketing_analog || '';
      heroGen.textContent = ma ? gl + '≈' + ma : gl;
    }
    const wfRt = document.getElementById('emp-wf-release-train');
    if (wfRt) wfRt.textContent = cur;
    const wfKind = document.getElementById('emp-wf-release-kind');
    if (wfKind) wfKind.textContent = kind;
    const tag = document.getElementById('emp-wf-tagline');
    if (tag) {
      let suffix = '';
      if (data.is_major_day) suffix = ' · major 日（100 天）';
      else if (data.is_installer_day) suffix = ' · installer 日（10 天）';
      else if (data.next_kind_hint === 'installer') suffix = ' · 下一 bump → installer';
      const src = data._source === 'api' ? 'live API' : '静态 SSOT';
      const genTxt = data.decennial_generation_label
        ? ` · ${data.decennial_generation_label}（十日线≈${data.marketing_analog || 'v' + data.decennial_generation}）`
        : '';
      const nextAnchor = data.next_decennial_anchor ? ` · 下代锚 ${data.next_decennial_anchor}` : '';
      tag.textContent = `release_train ${cur}（day ${dayIdx}）${genTxt}${suffix}${nextAnchor} · 双轨 v10 · ${src}`;
    }
  }

  async function refresh() {
    apply(await fetchSnapshot());
  }

  return { refresh, fetchSnapshot, apply, enrichSnapshot };
})();

/* ==========================================================================
 * 5b. employeeWorkflow — 员工工作流程 Tab
 * ========================================================================== */
const EmployeeWorkflow = (() => {
  let mermaidLoadPromise = null;
  let diagramRendered = false;

  function copyInner(fromId, toId) {
    const src = document.getElementById(fromId);
    const dst = document.getElementById(toId);
    if (src && dst) dst.innerHTML = src.innerHTML;
  }

  function copyText(fromId, toId) {
    const src = document.getElementById(fromId);
    const dst = document.getElementById(toId);
    if (src && dst) dst.textContent = src.textContent;
  }

  function loadMermaid() {
    if (window.mermaid) return Promise.resolve(window.mermaid);
    if (mermaidLoadPromise) return mermaidLoadPromise;
    mermaidLoadPromise = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
      s.async = true;
      s.onload = () => {
        if (!window.mermaid) {
          reject(new Error('mermaid unavailable'));
          return;
        }
        window.mermaid.initialize({
          startOnLoad: false,
          theme: 'dark',
          securityLevel: 'loose',
          flowchart: { htmlLabels: true, curve: 'basis' },
          themeVariables: {
            primaryColor: '#1a2332',
            primaryTextColor: '#e6edf3',
            primaryBorderColor: '#58e2c2',
            lineColor: '#58a0ff',
            secondaryColor: '#151b28',
            tertiaryColor: '#0d1117',
            clusterBkg: 'rgba(88,226,194,0.06)',
            clusterBorder: 'rgba(88,226,194,0.28)',
            titleColor: '#58e2c2',
            edgeLabelBackground: '#151b28',
          },
        });
        resolve(window.mermaid);
      };
      s.onerror = () => reject(new Error('mermaid script load failed'));
      document.head.appendChild(s);
    });
    return mermaidLoadPromise;
  }

  function activateDiagramViews() {
    if (window.EmpWfRadialGraph && typeof window.EmpWfRadialGraph.bindToolbar === 'function') {
      window.EmpWfRadialGraph.bindToolbar();
    }
  }

  async function renderMermaidIn(root, opts) {
    const scope = root || document.getElementById('s-workflow');
    if (!scope) return;
    const pending = Array.from(
      scope.querySelectorAll('.mermaid:not([data-processed="true"]):not([hidden])'),
    );
    if (!pending.length) return;
    const mermaid = opts && opts.mermaid ? opts.mermaid : await loadMermaid();
    const errors = [];
    for (const node of pending) {
      try {
        await mermaid.run({ nodes: [node] });
        node.setAttribute('data-processed', 'true');
        node.classList.remove('emp-wf-mermaid-err');
      } catch (err) {
        errors.push(err);
        node.classList.add('emp-wf-mermaid-err');
        console.warn('Mermaid 单段渲染失败', err);
      }
    }
    scope.querySelectorAll('.mermaid svg').forEach((svg) => {
      svg.removeAttribute('width');
      svg.removeAttribute('height');
      svg.style.maxWidth = '100%';
      svg.style.height = 'auto';
    });
    if (window.EmpWfNodeStaff && typeof window.EmpWfNodeStaff.bindMermaid === 'function') {
      await window.EmpWfNodeStaff.bindMermaid(scope);
    }
    const okCount = pending.filter((n) => n.getAttribute('data-processed') === 'true').length;
    if (errors.length && okCount === 0) throw errors[0];
  }

  let renderingArchitecture = false;

  async function renderArchitectureDiagram() {
    if (window.EmpWfRadialGraph && typeof window.EmpWfRadialGraph.setView === 'function') {
      window.EmpWfRadialGraph.setView('radial');
    }
  }

  async function loadStepAudit() {
    return dashFetchJson('.cache/xcmax/xcmax-step-employee-coverage.json?v=20260603w', { cache: 'no-store' });
  }

  async function loadPathEmployee() {
    return dashFetchJson('.cache/xcmax/xcmax-path-employee-coverage.json?v=20260603w', { cache: 'no-store' });
  }

  async function loadStepMap() {
    return dashFetchJson('six_line_employee_map.json?v=20260603u', { cache: 'no-store' });
  }

  function fmtPct(n) {
    if (n == null || Number.isNaN(Number(n))) return '—';
    return Number(n).toFixed(1);
  }

  function renderHero(stepAudit, pathPe) {
    const tag = document.getElementById('emp-wf-tagline');
    const rosterEl = document.getElementById('emp-wf-roster');
    const stepPctEl = document.getElementById('emp-wf-step-pct');
    const pathPctEl = document.getElementById('emp-wf-path-pct');

    const roster = stepAudit && stepAudit.roster_count != null ? stepAudit.roster_count : 52;
    if (rosterEl) rosterEl.textContent = String(roster);
    if (stepPctEl && stepAudit) stepPctEl.textContent = fmtPct(stepAudit.step_coverage_pct) + '%';
    if (pathPctEl && pathPe && pathPe.fully_bound_count != null) {
      const pct = pathPe.roster_count
        ? (pathPe.fully_bound_count / pathPe.roster_count * 100)
        : null;
      pathPctEl.textContent = pct != null ? fmtPct(pct) + '%' : '—';
    }

    if (tag && stepAudit) {
      tag.textContent =
        stepAudit.roster_in_steps_count + '/' + stepAudit.roster_count + ' 编制落六线步骤 · ' +
        (pathPe ? pathPe.fully_bound_count + '/' + pathPe.roster_count + ' 路径三元绑定' : '路径绑定见目录结构页') +
        ' · 手动重跑与 08:15 自动派发共用同一执行器';
    } else if (tag) {
      tag.textContent = '编制 52 人 · 清单驱动 vibe-coding · 运维面板可手动触发';
    }
  }

  async function activate() {
    diagramRendered = false;
    document.querySelectorAll('#emp-wf-arch-diagram .mermaid').forEach((n) => {
      n.removeAttribute('data-processed');
      n.classList.remove('emp-wf-mermaid-err');
    });
    await ReleaseTrain.refresh();
    activateDiagramViews();
    if (window.EmpWfRadialGraph) {
      if (typeof window.EmpWfRadialGraph.ensureRadialView === 'function') {
        window.EmpWfRadialGraph.ensureRadialView();
      }
      const radialRoot = document.getElementById('emp-wf-radial-root');
      if (radialRoot && typeof window.EmpWfRadialGraph.renderRadial === 'function') {
        window.EmpWfRadialGraph.renderRadial(radialRoot).catch(() => {});
      }
    }
    await renderArchitectureDiagram();
    const mapDoc = await loadStepMap();
    const stepAudit = await loadStepAudit();
    const pathPe = await loadPathEmployee();
    renderHero(stepAudit, pathPe);

    if (mapDoc) {
      LineCoverage.renderStepEmployeePanel(stepAudit, mapDoc);
      const wfPanel = document.getElementById('emp-wf-step-panel');
      if (wfPanel) {
        wfPanel.hidden = false;
        copyInner('step-employee-binding', 'emp-wf-step-binding');
        copyInner('step-employee-table', 'emp-wf-step-table');
        copyText('step-employee-foot', 'emp-wf-step-foot');
      }
    }

    if (pathPe) {
      LineCoverage.renderPathEmployeePanel(pathPe);
      const wfPathPanel = document.getElementById('emp-wf-path-panel');
      if (wfPathPanel) {
        wfPathPanel.hidden = false;
        copyInner('pe-employee-binding', 'emp-wf-path-binding');
        copyText('pe-duty-foot', 'emp-wf-path-foot');
      }
    }
  }

  window.__empWfShowMermaid = function () {
    diagramRendered = false;
    document.querySelectorAll('#emp-wf-arch-diagram .mermaid').forEach((n) => {
      n.removeAttribute('data-processed');
      n.hidden = false;
    });
    renderArchitectureDiagram();
  };

  return {
    activate,
    loadStepAudit,
    loadPathEmployee,
    renderArchitectureDiagram,
    renderMermaidIn,
    loadMermaid,
  };
})();

/* ==========================================================================
 * 5c. eventRail — 事件轨 Tab
 * ========================================================================== */
const EventRail = (() => {
  async function loadRoutesJson() {
    if (window.EventArchGraph && typeof window.EventArchGraph.loadRoutesJson === 'function') {
      return window.EventArchGraph.loadRoutesJson();
    }
    if (window.XCAGIApi && typeof window.XCAGIApi.fetchJson === 'function') {
      return window.XCAGIApi.fetchJson('FHD/config/six_line_event_routes.json', { cache: 'no-store' });
    }
    return null;
  }

  async function fetchLiveStatus() {
    const paths = [
      '/api/xcmax/production-line/event-rail/status',
      '/api/admin/production-line/event-rail/status',
    ];
    const bases = [''];
    if (location.protocol === 'file:') bases.push('http://127.0.0.1:5000');
    for (const base of bases) {
      for (const path of paths) {
        try {
          const url = base ? base + path : path;
          const r = await fetch(url, { signal: AbortSignal.timeout(1500) });
          if (r.ok) {
            const ct = (r.headers.get('content-type') || '').toLowerCase();
            if (ct.includes('text/html')) continue;
            const j = await r.json();
            if (j && j.data) return { live: true, data: j.data };
          }
        } catch (_) { /* next */ }
      }
    }
    return { live: false, data: null };
  }

  function applyStats(cfg, liveWrap) {
    const ops = document.getElementById('er-ops-routes');
    const cross = document.getElementById('er-cross-routes');
    const backlog = document.getElementById('er-backlog');
    const st = document.getElementById('er-live');
    const inc = document.getElementById('er-incident-pending');
    const tag = document.getElementById('event-rail-tagline');
    const live = liveWrap && liveWrap.data;
    if (live) {
      if (ops) ops.textContent = String(live.operations_routes ?? '—');
      if (cross) cross.textContent = String(live.cross_line_routes ?? '—');
      if (backlog) backlog.textContent = String(live.digest_backlog_pending ?? 0);
      if (inc) inc.textContent = String(live.incident_pending ?? 0);
      if (st) {
        st.textContent = '在线';
        st.style.color = 'var(--green)';
      }
      if (tag) {
        tag.textContent =
          'SSOT · live · backlog ' + (live.digest_backlog_pending ?? 0) +
          ' · incident ' + (live.incident_pending ?? 0);
      }
      return live.recent_route_ids || null;
    }
    if (cfg) {
      if (ops) ops.textContent = String((cfg.operations_line || []).length);
      if (cross) cross.textContent = String((cfg.cross_line || []).length);
      if (backlog) backlog.textContent = '—';
      if (inc) inc.textContent = '—';
      if (tag) tag.textContent = 'SSOT · ' + (cfg.version || '') + ' · 静态预览（启动 FastAPI 可看 live）';
    }
    if (st) {
      st.textContent = '静态';
      st.style.color = 'var(--muted)';
    }
    return null;
  }

  async function activate() {
    if (document.body.classList.contains('embed-workflow')) return;
    const [cfg, liveWrap] = await Promise.all([loadRoutesJson(), fetchLiveStatus()]);
    const recentIds = applyStats(cfg, liveWrap);
    const hi = recentIds ? new Set(recentIds) : null;
    if (window.EventRailUi && typeof window.EventRailUi.renderDetail === 'function') {
      window.EventRailUi.renderDetail(cfg);
    }
    const root = document.getElementById('event-arch-root');
    if (root && window.EventArchGraph && typeof window.EventArchGraph.render === 'function') {
      if (typeof window.SAxis === 'undefined') {
        await new Promise((r) => requestAnimationFrame(r));
      }
      await window.EventArchGraph.render(root, hi);
    }
    const legacy = document.querySelector('#emp-wf-event-rail .emp-wf-event-mermaid');
    if (legacy && window.EmployeeWorkflow && typeof EmployeeWorkflow.renderMermaidIn === 'function') {
      const wrap = document.querySelector('#emp-wf-event-rail .emp-wf-diagram-wrap--event');
      if (wrap) {
        legacy.removeAttribute('data-processed');
        try {
          await EmployeeWorkflow.renderMermaidIn(wrap);
        } catch (_) { /* optional legacy block */ }
      }
    }
  }

  return { activate, loadRoutesJson, fetchLiveStatus };
})();

/* ==========================================================================
 * 6. init — 入口
 * ========================================================================== */
function xcmiInit() {
  Router.bind();
  const params = new URLSearchParams(window.location.search);
  const embed = params.get('embed');
  const hashTab = (window.location.hash || '').replace(/^#/, '');
  const validTabs = new Set(['loops', 'workflow', 'events', 'monitor', 'aibiz', 'tree', 'gaps', 'roadmap', 'evolution']);
  if (embed === 'shell') {
    document.body.classList.add('embed-shell');
    const viewPref = (params.get('view') || '').trim().toLowerCase();
    let tab = viewPref === 'mermaid' ? 'workflow' : 'loops';
    if (hashTab.startsWith('s-')) tab = hashTab.slice(2);
    else if (validTabs.has(hashTab)) tab = hashTab;
    /* 运维台嵌入：?view=mermaid 固定员工工作流，避免旧 #s-loops 露出六线/事件轨 */
    if (viewPref === 'mermaid') tab = 'workflow';
    if (validTabs.has(tab)) Router.show(tab, { skipScroll: true });
    if (tab === 'workflow' || viewPref === 'mermaid') {
      document.body.classList.add('embed-workflow');
      if (
        window.EmpWfRadialGraph &&
        typeof window.EmpWfRadialGraph.ensureRadialView === 'function'
      ) {
        window.EmpWfRadialGraph.ensureRadialView();
        const root = document.getElementById('emp-wf-radial-root');
        if (root && typeof window.EmpWfRadialGraph.renderRadial === 'function') {
          window.EmpWfRadialGraph.renderRadial(root).catch(() => {});
        }
      }
    }
  } else if (embed === 'loops' || hashTab === 's-loops') {
    document.body.classList.add('embed-loops', 'embed-shell');
    Router.show('loops', { skipScroll: true });
  } else if (validTabs.has(hashTab)) {
    Router.show(hashTab, { skipScroll: true });
  }
  SAxis.activate();
  LineView.bind();
  Ops.bind();
  Gaps.bindCollapsibles();
  Gaps.activate();
  LineCoverage.activate().catch(() => {});
  ReleaseTrain.refresh().catch(() => {});
  setTimeout(Ops.refresh, 1500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', xcmiInit);
} else {
  xcmiInit();
}

/* 日更行动条目渲染模块按需注入（断点清单=补丁 / 路线图=更新）；失败静默，不影响主面板 */
(function loadActionItemsModule() {
  try {
    if (window.EmpWfActionItems || document.getElementById('emp-wf-action-items-js')) return;
    let base = 'docs/xcagi-dashboard/';
    const scripts = document.getElementsByTagName('script');
    for (let i = 0; i < scripts.length; i++) {
      const src = scripts[i].getAttribute('src') || '';
      const idx = src.indexOf('docs/xcagi-dashboard/app.js');
      if (idx >= 0) { base = src.slice(0, idx) + 'docs/xcagi-dashboard/'; break; }
    }
    const s = document.createElement('script');
    s.id = 'emp-wf-action-items-js';
    s.src = base + 'emp-wf-action-items.js?v=20260606k';
    s.defer = true;
    document.head.appendChild(s);
  } catch (_e) {
    /* ignore */
  }
})();
