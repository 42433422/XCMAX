/**
 * 时间轨 SW / SS / SA 节点 ↔ AI 业务 Tab 表面巡检（截图画廊 + 刷新）
 */
const EmpWfSurfaceAudit = (() => {
  const NODES = {
    SW: { terminal: 'web', lane: 'P-W', title: 'P-W 网站截图' },
    SS: { terminal: 'software', lane: 'P-S', title: 'P-S 软件截图' },
    SA: { terminal: 'app', lane: 'P-App', title: 'P-App 移动/WebView 截图' },
  };

  function api(path) {
    if (window.XCAGIApi && typeof window.XCAGIApi.url === 'function') return window.XCAGIApi.url(path);
    return path;
  }

  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function isSurfaceAuditNode(nodeId) {
    return Object.prototype.hasOwnProperty.call(NODES, String(nodeId || '').trim());
  }

  function actionsHtml(nodeId) {
    const meta = NODES[nodeId];
    if (!meta) return '';
    return (
      '<div class="emp-wf-popover-actions" data-emp-wf-surface-node="' + escapeHtml(nodeId) + '">' +
      '<div class="emp-wf-popover-role">表面巡检 · 已对接</div>' +
      '<p class="emp-wf-popover-scope">FHD 本地 <code>make surface-audit-app</code> · Playwright Web/WebView' +
      (nodeId === 'SA' ? ' + adb 模拟器原生屏' : '') +
      '</p>' +
      '<div class="emp-wf-popover-action-row">' +
      '<button type="button" class="emp-wf-popover-btn" data-emp-wf-sa-act="gallery">查看全部截图</button>' +
      '<button type="button" class="emp-wf-popover-btn emp-wf-popover-btn--primary" data-emp-wf-sa-act="refresh">↻ 刷新巡检</button>' +
      '</div>' +
      '<button type="button" class="emp-wf-popover-btn emp-wf-popover-btn--ghost" data-emp-wf-sa-act="aibiz">打开 AI 业务 Tab</button>' +
      '<p class="emp-wf-popover-foot">API <code>/api/xcmax/aibiz/app-terminal</code> · lane ' + escapeHtml(meta.lane) + '</p>' +
      '</div>'
    );
  }

  function goAibizTab() {
    if (typeof window.go === 'function') window.go('aibiz');
    else if (typeof Router !== 'undefined' && Router.show) Router.show('aibiz');
  }

  async function refreshTerminal(terminal, refresh) {
    const biz = window.MonAiBiz;
    if (!biz) return;
    if (terminal === 'web' && biz.refreshTerminalWeb) return biz.refreshTerminalWeb(!!refresh);
    if (terminal === 'software' && biz.refreshTerminalDesk) return biz.refreshTerminalDesk(!!refresh);
    if (terminal === 'app' && biz.refreshTerminalApp) return biz.refreshTerminalApp(!!refresh);
  }

  function waitForMonAiBiz(timeoutMs) {
    return new Promise((resolve) => {
      const deadline = Date.now() + (timeoutMs || 3000);
      (function poll() {
        const biz = window.MonAiBiz;
        if (biz && biz.openTerminalScreenshotGallery) return resolve(biz);
        if (Date.now() >= deadline) return resolve(null);
        setTimeout(poll, 150);
      })();
    });
  }

  async function openGallery(nodeId, refresh) {
    const meta = NODES[nodeId];
    if (!meta) return;
    goAibizTab();
    if (refresh) await refreshTerminal(meta.terminal, true);
    const biz = window.MonAiBiz;
    if (biz && biz.openTerminalScreenshotGallery) {
      await biz.openTerminalScreenshotGallery(meta.terminal);
      return;
    }
    const apiPath =
      meta.terminal === 'web'
        ? '/api/xcmax/aibiz/web-terminal'
        : meta.terminal === 'software'
          ? '/api/xcmax/aibiz/desk-terminal'
          : '/api/xcmax/aibiz/app-terminal';
    const q = refresh ? '?refresh=1&compact=0' : '?compact=0';
    try {
      const r = await fetch(api(apiPath + q), { cache: 'no-store' });
      const j = await r.json();
      const pages = (j.data && j.data.surface_audit && j.data.surface_audit.pages) || [];
      // mon-ai-biz.js 可能在 Tab 切换后才挂载：等它就绪再开画廊
      const lateBiz = await waitForMonAiBiz(3000);
      if (lateBiz) await lateBiz.openTerminalScreenshotGallery(meta.terminal, pages);
    } catch (_) { /* offline */ }
  }

  function bindActions(popoverEl, nodeId) {
    if (!popoverEl || !isSurfaceAuditNode(nodeId)) return;
    const block = popoverEl.querySelector('[data-emp-wf-surface-node="' + nodeId + '"]');
    if (!block) return;
    block.querySelectorAll('[data-emp-wf-sa-act]').forEach((btn) => {
      btn.addEventListener('click', async (ev) => {
        ev.stopPropagation();
        const act = btn.getAttribute('data-emp-wf-sa-act');
        if (act === 'aibiz') {
          goAibizTab();
          await refreshTerminal(NODES[nodeId].terminal, false);
          return;
        }
        if (act === 'refresh') {
          btn.disabled = true;
          btn.textContent = '巡检中…';
          try {
            await openGallery(nodeId, true);
          } finally {
            btn.disabled = false;
            btn.textContent = '↻ 刷新巡检';
          }
          return;
        }
        if (act === 'gallery') {
          await openGallery(nodeId, false);
        }
      });
    });
  }

  /** 辐射图节点双击：直达截图画廊 */
  function bindRadialDoubleOpen(layer) {
    if (!layer) return;
    layer.querySelectorAll('.emp-wf-radial-node').forEach((el) => {
      const nodeId = (el.dataset.empWfNode || '').trim();
      if (!isSurfaceAuditNode(nodeId)) return;
      if (el.getAttribute('data-emp-wf-sa-dbl') === '1') return;
      el.setAttribute('data-emp-wf-sa-dbl', '1');
      el.title = (el.title || '') + ' · 双击打开截图画廊';
      el.addEventListener('dblclick', (ev) => {
        ev.stopPropagation();
        openGallery(nodeId, false);
      });
    });
  }

  return { isSurfaceAuditNode, actionsHtml, bindActions, bindRadialDoubleOpen, openGallery };
})();

window.EmpWfSurfaceAudit = EmpWfSurfaceAudit;
