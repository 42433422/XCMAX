/**
 * 事件轨 · 按业务步骤的工作逻辑架构（蛇形/扁平行，与 loops 同序，内容为触发→派发）
 */
const EventWorkflowSnake = (() => {
  const LINE_ORDER = {
    ops_acquisition: ['O1', 'O2', 'O3', 'O4', 'O5', 'O6', 'O7', 'O8', 'O9', 'O10'],
    ops_partner: ['B1', 'B2', 'B3', 'B4', 'B5'],
    prod_mod: ['P2', 'P3', 'P6'],
  };

  const LINE_LABEL = {
    ops_acquisition: 'O-A · 获客线',
    ops_partner: 'O-B · 伙伴线',
    prod_mod: 'P-M · Mod 线',
  };

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function stepOrderFromLoops(lineId) {
    const loop = document.querySelector('.loop--five-line[data-five-line="' + lineId + '"]');
    if (!loop) return LINE_ORDER[lineId] || [];
    const ids = [];
    loop.querySelectorAll('.flow-node').forEach((node) => {
      const sid = node.getAttribute('data-ops-step') || node.getAttribute('data-prod-step');
      if (sid && !ids.includes(sid)) ids.push(sid);
    });
    return ids.length ? ids : (LINE_ORDER[lineId] || []);
  }

  function loopsStepMeta(lineId, stepId) {
    const loop = document.querySelector('.loop--five-line[data-five-line="' + lineId + '"]');
    if (!loop) return null;
    const node = loop.querySelector(
      '[data-ops-step="' + stepId + '"],[data-prod-step="' + stepId + '"]',
    );
    if (!node) return null;
    const name = node.querySelector('.node-name');
    const desc = node.querySelector('.node-desc');
    const staff = node.querySelector('.node-dept-staff');
    return {
      title: name ? name.textContent.trim() : '',
      desc: desc ? desc.textContent.trim() : '',
      staffHtml: staff ? staff.innerHTML : '',
    };
  }

  function routesForLine(cfg, lineId) {
    return (cfg.operations_line || []).filter((r) => r.six_line === lineId);
  }

  function routeByStep(routes, stepId) {
    return routes.find((r) => (r.step_id || r.line_step) === stepId) || null;
  }

  function crossForStep(cfg, stepId) {
    return (cfg.cross_line || []).filter((x) => x.from_step === stepId || x.to_step === stepId);
  }

  function actionBadge(action, priority) {
    const cls =
      action === 'digest_backlog'
        ? 'event-tag--backlog'
        : action === 'incident'
          ? 'event-tag--incident'
          : 'event-tag--none';
    const label = action === 'digest_backlog' ? 'backlog' : action || '未接线';
    return (
      '<span class="node-tag event-tag ' + cls + '">' +
      escapeHtml(label) + (priority ? ' · ' + escapeHtml(priority) : '') +
      '</span>'
    );
  }

  function buildStepNode(stepId, idx, route, catalog, loopsMeta, crossLines) {
    const cat = (catalog && catalog[stepId]) || {};
    const loopsTitle = loopsMeta && loopsMeta.title;
    const numTitle = loopsTitle || (idx + 1) + '. ' + (cat.title || stepId);
    const triggers = route && route.triggers && route.triggers.length
      ? route.triggers.join(' · ')
      : '—';
    const statusIn = route && route.status_in && route.status_in.length
      ? route.status_in.join(' | ')
      : '—';
    let dispatch = '未接线 — 见下方路由明细';
    if (route) {
      if (route.action === 'digest_backlog') {
        dispatch =
          '派发 backlog → ' + (route.dispatch_line || 'P-S') +
          ' · ' + (route.list_kind || 'patches') +
          ' · 汇入 08:00 补丁 MD';
      } else if (route.action === 'incident') {
        dispatch =
          '派发 ' + (route.event_type || 'incident') + ' → incident_bus';
        if (route.priority === 'P0') dispatch += ' · 可插队 08:15';
      }
      if (route.also_incident) {
        dispatch += ' + ' + route.also_incident;
      }
    }
    let crossHtml = '';
    if (crossLines.length) {
      crossHtml =
        '<div class="node-event-cross">跨线：' +
        crossLines.map((c) =>
          escapeHtml((c.from_step || '') + '→' + (c.to_step || '') + ' ' + (c.action || '')),
        ).join(' · ') +
        '</div>';
    }

    const el = document.createElement('div');
    el.className = 'flow-node event-wf-node';
    el.setAttribute('data-event-step', stepId);
    if (route && route.id) el.dataset.eventRouteId = route.id;
    el.innerHTML =
      '<div class="node-content">' +
      '<div class="node-head">' +
      '<span class="node-name">' + escapeHtml(numTitle) + '</span>' +
      actionBadge(route && route.action, route && route.priority) +
      '</div>' +
      '<div class="node-desc event-wf-triggers"><strong>触发</strong> ' + escapeHtml(triggers) + '</div>' +
      '<div class="node-desc event-wf-status">status_in: ' + escapeHtml(statusIn) + '</div>' +
      '<div class="node-event-dispatch">' + escapeHtml(dispatch) + '</div>' +
      (loopsMeta && loopsMeta.desc
        ? '<div class="node-desc event-wf-task">' + escapeHtml(loopsMeta.desc) + '</div>'
        : '') +
      crossHtml +
      (loopsMeta && loopsMeta.staffHtml
        ? '<div class="node-dept-staff">' + loopsMeta.staffHtml + '</div>'
        : '') +
      '</div>';
    return el;
  }

  function renderLine(root, cfg, lineId) {
    if (!root || !cfg) return;
    const catalog = cfg.step_catalog || {};
    const routes = routesForLine(cfg, lineId);
    const steps = stepOrderFromLoops(lineId);
    root.innerHTML = '';
    root.classList.remove('is-loading', 'is-error');

    const wrap = document.createElement('div');
    wrap.className = 'event-wf-loop loop loop--five-line loop--event-wf';
    wrap.dataset.fiveLine = lineId;

    const head = document.createElement('div');
    head.className = 'loop-head';
    head.innerHTML =
      '<div class="loop-title">' + escapeHtml(LINE_LABEL[lineId] || lineId) + '</div>' +
      '<div class="loop-subtitle">事件驱动工作逻辑 · 触发匹配 → 完成任务 → incident / backlog</div>';
    wrap.appendChild(head);

    const body = document.createElement('div');
    body.className = 'loop-body s-axis';
    steps.forEach((stepId, idx) => {
      const route = routeByStep(routes, stepId);
      const loopsMeta = loopsStepMeta(lineId, stepId);
      const crossLines = crossForStep(cfg, stepId);
      body.appendChild(buildStepNode(stepId, idx, route, catalog, loopsMeta, crossLines));
    });
    wrap.appendChild(body);
    root.appendChild(wrap);

    if (typeof SAxis !== 'undefined' && typeof SAxis.layoutBody === 'function') {
      delete body.dataset.sAxisDone;
      SAxis.layoutBody(body);
      SAxis.bindExpand(wrap);
    }
  }

  function bindLineTabs(cfg, onSelect) {
    const tabs = document.querySelectorAll('[data-event-line]');
    if (!tabs.length) return;
    tabs.forEach((btn) => {
      btn.addEventListener('click', () => {
        const lineId = btn.getAttribute('data-event-line');
        tabs.forEach((b) => {
          const on = b === btn;
          b.classList.toggle('active', on);
          b.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        if (typeof onSelect === 'function') onSelect(lineId);
      });
    });
  }

  return { renderLine, bindLineTabs, LINE_ORDER };
})();

window.EventWorkflowSnake = EventWorkflowSnake;
