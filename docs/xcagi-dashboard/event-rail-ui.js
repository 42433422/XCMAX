/**
 * 事件轨明细 — 按 event_type / 业务域分组的路由卡
 */
const EventRailUi = (() => {
  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function badgeClass(action) {
    if (action === 'digest_backlog') return 'emp-wf-badge--backlog';
    if (action === 'incident') return 'emp-wf-badge--incident';
    return 'emp-wf-badge--route';
  }

  function routeCard(r, catalog) {
    const step = r.step_id || r.line_step || r.from_step || '—';
    const title = (catalog && catalog[step] && catalog[step].title) || step;
    const triggers = (r.triggers || []).join(' · ') || '—';
    const et = r.event_type || r.also_incident || '—';
    const action = r.action || '—';
    const pri = r.priority || '';
    const dispatch = r.dispatch_line ? ' → ' + r.dispatch_line : '';
    const cross = r.from_step && r.to_step ? r.from_step + ' → ' + r.to_step : '';
    return (
      '<li class="event-route-card">' +
      '<div class="event-route-card__head">' +
      '<span class="emp-wf-badge ' + badgeClass(action) + '">' + escapeHtml(action) + '</span>' +
      '<strong>' + escapeHtml(title) + '</strong>' +
      (pri ? '<span class="event-route-pri">' + escapeHtml(pri) + '</span>' : '') +
      '</div>' +
      '<div class="event-route-card__meta">' +
      (cross ? '<span>交叉 ' + escapeHtml(cross) + '</span>' : '<span>步骤 ' + escapeHtml(step) + '</span>') +
      '<span><code>' + escapeHtml(et) + '</code></span>' +
      (dispatch ? '<span>派发' + escapeHtml(dispatch) + '</span>' : '') +
      '</div>' +
      '<div class="event-route-card__triggers">触发：' + escapeHtml(triggers) + '</div>' +
      '</li>'
    );
  }

  function groupRoutes(list, catalog, lineFilter) {
    const filtered = (list || []).filter((r) => {
      if (!lineFilter) return true;
      const line = r.six_line || '';
      return line === lineFilter;
    });
    const byType = new Map();
    for (const r of filtered) {
      const key = r.event_type || r.action || 'other';
      if (!byType.has(key)) byType.set(key, []);
      byType.get(key).push(r);
    }
    let html = '';
    for (const [key, items] of byType) {
      html += '<div class="event-route-group"><h4 class="event-route-group__title">' +
        escapeHtml(key) + '</h4><ul class="event-route-list">';
      for (const r of items) html += routeCard(r, catalog);
      html += '</ul></div>';
    }
    return html || '<p class="muted">暂无路由</p>';
  }

  function renderDetail(cfg) {
    const root = document.getElementById('event-rail-detail');
    if (!root || !cfg) return;
    const catalog = cfg.step_catalog || {};
    const oa = document.getElementById('event-rail-ops-oa');
    const ob = document.getElementById('event-rail-ops-ob');
    const pm = document.getElementById('event-rail-prod-pm');
    const cross = document.getElementById('event-rail-cross');
    const inc = document.getElementById('event-rail-incident');
    if (oa) {
      oa.innerHTML = groupRoutes(cfg.operations_line, catalog, 'ops_acquisition');
    }
    if (ob) {
      ob.innerHTML = groupRoutes(cfg.operations_line, catalog, 'ops_partner');
    }
    if (pm) {
      const pmRoutes = (cfg.operations_line || []).filter((r) => r.six_line === 'prod_mod');
      const pmInc = (cfg.incident_defaults || []).filter((r) => r.six_line === 'prod_mod');
      pm.innerHTML = groupRoutes(pmRoutes.concat(pmInc), catalog, null);
    }
    if (cross) {
      cross.innerHTML = groupRoutes(cfg.cross_line, catalog, null);
    }
    if (inc) {
      inc.innerHTML = groupRoutes(
        (cfg.incident_defaults || []).filter((r) => r.six_line !== 'prod_mod'),
        catalog,
        null,
      );
    }
  }

  return { renderDetail };
})();

window.EventRailUi = EventRailUi;
