/**
 * 日更架构图节点点击 → 主责/协作员工弹层（Mermaid + 辐射图共用）
 */
const EmpWfNodeStaff = (() => {
  const MAP_URL = 'docs/xcagi-dashboard/daily_digest_node_employees.json?v=20260606a';
  const LABELS_ZH_URL = 'docs/xcagi-dashboard/employee_labels_zh.json?v=20260604b';
  const SIX_LINE_URL = 'six_line_employee_map.json?v=20260603u';
  const POPOVER_IDS = {
    workflow: 'emp-wf-node-popover',
    events: 'event-arch-node-popover',
  };

  let nodeMapDoc = null;
  let sixLineDoc = null;
  let labelById = Object.create(null);
  let loadPromise = null;
  let popoverEl = null;
  let activeNodeId = '';
  let dismissBound = false;

  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[c]));
  }

  function uniq(arr) {
    const out = [];
    const seen = new Set();
    for (const x of arr || []) {
      const k = String(x || '').trim();
      if (!k || seen.has(k)) continue;
      seen.add(k);
      out.push(k);
    }
    return out;
  }

  function mergeStaff(base, extra) {
    return {
      primary: uniq([...(base.primary || []), ...(extra.primary || [])]),
      support: uniq([...(base.support || []), ...(extra.support || [])]),
    };
  }

  function staffFromSixLine(refs) {
    const primary = [];
    const support = [];
    if (!sixLineDoc || !sixLineDoc.lines || !refs) return { primary, support };
    for (const ref of refs) {
      const block = sixLineDoc.lines[ref.line];
      const step = block && block.steps ? block.steps[ref.step] : null;
      if (!step) continue;
      primary.push(...(step.primary || []));
      support.push(...(step.support || []));
    }
    return { primary: uniq(primary), support: uniq(support) };
  }

  async function ensureData() {
    if (nodeMapDoc) return nodeMapDoc;
    if (loadPromise) return loadPromise;
    loadPromise = (async () => {
      const fetchJson =
        window.XCAGIApi && typeof window.XCAGIApi.fetchJson === 'function'
          ? (u) => window.XCAGIApi.fetchJson(u, { cache: 'no-store' })
          : async (u) => {
              const r = await fetch(u, { cache: 'no-store' });
              if (!r.ok) return null;
              const ct = (r.headers.get('content-type') || '').toLowerCase();
              if (ct.includes('text/html')) return null;
              try {
                return await r.json();
              } catch {
                return null;
              }
            };
      const [mapDoc, zhDoc, sixDoc] = await Promise.all([
        fetchJson(MAP_URL),
        fetchJson(LABELS_ZH_URL),
        fetchJson(SIX_LINE_URL),
      ]);
      if (!mapDoc) throw new Error('员工映射表加载失败');
      nodeMapDoc = mapDoc;
      if (nodeMapDoc.employee_labels) Object.assign(labelById, nodeMapDoc.employee_labels);
      if (zhDoc && zhDoc.labels) Object.assign(labelById, zhDoc.labels);
      if (sixDoc) sixLineDoc = sixDoc;
      return nodeMapDoc;
    })();
    return loadPromise;
  }

  /** 弹层展示用：优先中文岗位名 */
  function employeeDisplayName(id) {
    const key = String(id || '').trim();
    if (!key) return '（未命名编制）';
    const zh = labelById[key];
    if (zh && zh !== key) return zh;
    return '编制「' + key + '」';
  }

  function hasChineseLabel(id) {
    const key = String(id || '').trim();
    const zh = labelById[key];
    return !!(zh && zh !== key);
  }

  function resolveNode(nodeId) {
    const raw = nodeMapDoc && nodeMapDoc.nodes ? nodeMapDoc.nodes[nodeId] : null;
    if (!raw) return null;
    let staff = {
      primary: uniq(raw.primary || []),
      support: uniq(raw.support || []),
    };
    if (raw.six_line && raw.six_line.length) {
      staff = mergeStaff(staffFromSixLine(raw.six_line), staff);
    }
    return {
      id: nodeId,
      name: raw.name || nodeId,
      scope: raw.scope || '',
      ...staff,
    };
  }

  function staffListHtml(ids, role) {
    if (!ids || !ids.length) {
      return '<li class="emp-wf-popover-empty">（本步骤暂无' + escapeHtml(role) + '）</li>';
    }
    return ids
      .map((id) => {
        const name = employeeDisplayName(id);
        const tech =
          hasChineseLabel(id)
            ? '<span class="emp-wf-popover-tech" title="编制 ID（技术标识）">' +
              escapeHtml(id) +
              '</span>'
            : '';
        return (
          '<li class="emp-wf-popover-person">' +
          '<span class="emp-wf-popover-name">' +
          escapeHtml(name) +
          '</span>' +
          tech +
          '</li>'
        );
      })
      .join('');
  }

  function mountPopoverOnBody(el) {
    if (el && el.parentElement !== document.body) {
      document.body.appendChild(el);
    }
  }

  function popoverKindForAnchor(anchorEl) {
    if (anchorEl && anchorEl.closest && anchorEl.closest('#event-arch-root, #event-arch-diagram, #s-events')) {
      return 'events';
    }
    return 'workflow';
  }

  function ensurePopover(anchorEl) {
    const kind = popoverKindForAnchor(anchorEl);
    const id = POPOVER_IDS[kind];
    let el = document.getElementById(id);
    if (!el) {
      el = document.createElement('div');
      el.id = id;
      el.className = 'emp-wf-node-popover';
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-modal', 'false');
      el.setAttribute('aria-label', '步骤员工');
      el.hidden = true;
    }
    mountPopoverOnBody(el);
    document.querySelectorAll('.emp-wf-node-popover').forEach((node) => {
      if (node !== el) node.hidden = true;
    });
    popoverEl = el;
    bindDismissOnce();
    return el;
  }

  function bindDismissOnce() {
    if (dismissBound) return;
    dismissBound = true;
    document.addEventListener('click', (ev) => {
      const open = document.querySelector('.emp-wf-node-popover:not([hidden])');
      if (!open) return;
      if (open.contains(ev.target)) return;
      if (ev.target.closest && ev.target.closest('.emp-wf-radial-node, g.node')) return;
      hidePopover();
    });
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') hidePopover();
    });
  }

  function positionPopover(anchor) {
    const el = ensurePopover(anchor);
    const rect = anchor && anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : null;
    const pad = 12;
    const w = Math.min(360, window.innerWidth - pad * 2);
    el.style.width = w + 'px';
    el.hidden = false;
    el.style.visibility = 'hidden';
    const box = el.getBoundingClientRect();
    let left = rect ? rect.left + rect.width / 2 - box.width / 2 : pad;
    let top = rect ? rect.bottom + 10 : pad + 80;
    left = Math.max(pad, Math.min(left, window.innerWidth - box.width - pad));
    if (top + box.height > window.innerHeight - pad) {
      top = rect ? rect.top - box.height - 10 : window.innerHeight - box.height - pad;
    }
    top = Math.max(pad, top);
    el.style.left = left + 'px';
    el.style.top = top + 'px';
    el.style.visibility = 'visible';
  }

  function hidePopover() {
    activeNodeId = '';
    document.querySelectorAll('.emp-wf-node-popover').forEach((el) => {
      el.hidden = true;
    });
    popoverEl = null;
    document.querySelectorAll('.emp-wf-radial-node.is-selected, g.node.emp-wf-node-selected').forEach((n) => {
      n.classList.remove('is-selected', 'emp-wf-node-selected');
    });
  }

  async function show(nodeId, anchorEl) {
    await ensureData();
    const info = resolveNode(nodeId);
    const el = ensurePopover(anchorEl);
    if (!info) {
      el.innerHTML =
        '<div class="emp-wf-popover-head"><strong>' +
        escapeHtml(nodeId) +
        '</strong></div><p class="emp-wf-popover-miss">暂无该步骤的员工映射，请在仓库 <code>docs/xcagi-dashboard/daily_digest_node_employees.json</code> 中补充主责/协作编制。</p>';
      positionPopover(anchorEl);
      return;
    }
    if (activeNodeId === nodeId && !el.hidden) {
      hidePopover();
      return;
    }
    activeNodeId = nodeId;
    document.querySelectorAll('.emp-wf-radial-node.is-selected, g.node.emp-wf-node-selected').forEach((n) => {
      n.classList.remove('is-selected', 'emp-wf-node-selected');
    });
    if (anchorEl && anchorEl.classList) {
      anchorEl.classList.add(anchorEl.classList.contains('emp-wf-radial-node') ? 'is-selected' : 'emp-wf-node-selected');
    }
    el.innerHTML =
      '<button type="button" class="emp-wf-popover-close" aria-label="关闭">×</button>' +
      '<div class="emp-wf-popover-head"><strong class="emp-wf-popover-step-title">' +
      escapeHtml(info.name) +
      '</strong></div>' +
      (info.scope
        ? '<p class="emp-wf-popover-scope">' + escapeHtml(info.scope) + '</p>'
        : '') +
      '<div class="emp-wf-popover-section"><div class="emp-wf-popover-role">主责编制</div><ul class="emp-wf-popover-list">' +
      staffListHtml(info.primary, '主责编制') +
      '</ul></div>' +
      '<div class="emp-wf-popover-section"><div class="emp-wf-popover-role">协作编制</div><ul class="emp-wf-popover-list">' +
      staffListHtml(info.support, '协作编制') +
      '</ul></div>' +
      (typeof EmpWfSurfaceAudit !== 'undefined' && EmpWfSurfaceAudit.isSurfaceAuditNode(nodeId)
        ? EmpWfSurfaceAudit.actionsHtml(nodeId)
        : '') +
      '<p class="emp-wf-popover-foot">点击空白处或按 Esc 关闭' +
      (typeof EmpWfSurfaceAudit !== 'undefined' && EmpWfSurfaceAudit.isSurfaceAuditNode(nodeId)
        ? ' · 双击节点打开截图画廊'
        : '') +
      '</p>';
    el.querySelector('.emp-wf-popover-close').addEventListener('click', (ev) => {
      ev.stopPropagation();
      hidePopover();
    });
    if (typeof EmpWfSurfaceAudit !== 'undefined') {
      EmpWfSurfaceAudit.bindActions(el, nodeId);
    }
    positionPopover(anchorEl);
  }

  function extractMermaidNodeId(gEl) {
    const id = gEl.id || '';
    let m = id.match(/flowchart-([A-Za-z0-9_]+)-\d+/);
    if (m) return m[1];
    m = id.match(/flowchart-([A-Za-z0-9_]+)$/);
    if (m) return m[1];
    const label = gEl.querySelector('.nodeLabel');
    if (label) {
      const t = (label.textContent || '').trim();
      for (const [nid, row] of Object.entries((nodeMapDoc && nodeMapDoc.nodes) || {})) {
        if (row.name && t.indexOf(row.name.slice(0, 8)) >= 0) return nid;
      }
    }
    return '';
  }

  async function bindMermaid(wrap) {
    await ensureData();
    const svg = wrap && wrap.querySelector('.mermaid svg');
    if (!svg) return;
    svg.querySelectorAll('g.node').forEach((g) => {
      const nodeId = extractMermaidNodeId(g);
      if (!nodeId || !(nodeMapDoc.nodes && nodeMapDoc.nodes[nodeId])) return;
      g.classList.add('emp-wf-node-clickable');
      g.style.cursor = 'pointer';
      if (g.getAttribute('data-emp-wf-bound') === '1') return;
      g.setAttribute('data-emp-wf-bound', '1');
      g.addEventListener('click', (ev) => {
        ev.stopPropagation();
        show(nodeId, g);
      });
    });
  }

  function bindRadial(layer) {
    if (!layer) return;
    ensureData()
      .then(() => {
      layer.querySelectorAll('.emp-wf-radial-node').forEach((el) => {
        const nodeId = (el.dataset.empWfNode || el.dataset.eventNode || '').trim();
        if (!nodeId) return;
        el.style.cursor = 'pointer';
        if (el.getAttribute('data-emp-wf-bound') === '1') return;
        el.setAttribute('data-emp-wf-bound', '1');
        el.addEventListener('click', (ev) => {
          const panHost =
            document.getElementById('emp-wf-radial-root') || document.getElementById('event-arch-root');
          if (panHost && panHost.dataset.panMoved === '1') return;
          ev.stopPropagation();
          show(nodeId, el);
        });
      });
    })
      .catch(() => {});
  }

  window.__empWfShowNodeStaff = (nodeId, anchor) => show(nodeId, anchor);

  return { ensureData, show, hidePopover, bindMermaid, bindRadial };
})();

window.EmpWfNodeStaff = EmpWfNodeStaff;
