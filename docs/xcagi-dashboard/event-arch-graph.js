/**
 * 事件轨主图：默认合并架构（阶段 A–D · radial-stage）；可切换步骤明细蛇形
 */
const EventArchGraph = (() => {
  let viewMode = 'merged';
  let activeLine = 'ops_acquisition';
  let tabsBound = false;
  let lastCfg = null;

  async function loadRoutesJson() {
    const urls = [
      'FHD/config/six_line_event_routes.json',
      '/xcmax-dashboard/FHD/config/six_line_event_routes.json',
    ];
    for (const u of urls) {
      const data =
        window.XCAGIApi && typeof window.XCAGIApi.fetchJson === 'function'
          ? await window.XCAGIApi.fetchJson(u, { cache: 'no-store' })
          : null;
      if (data) return data;
    }
    return null;
  }

  function normalizeHi(highlightRouteIds) {
    if (highlightRouteIds instanceof Set) return highlightRouteIds;
    if (Array.isArray(highlightRouteIds)) return new Set(highlightRouteIds);
    return null;
  }

  function highlightSnake(root, routeIds) {
    if (!root || !routeIds || !routeIds.size) return;
    root.querySelectorAll('.event-wf-node').forEach((n) => {
      const rid = n.dataset.eventRouteId;
      n.classList.toggle('event-wf-node--live', rid && routeIds.has(rid));
    });
  }

  async function renderMerged(root, hi) {
    if (!window.EventMergedArchGraph) {
      root.textContent = 'event-merged-arch-graph.js 未加载';
      return;
    }
    await EventMergedArchGraph.render(root, { highlightIds: hi });
  }

  async function renderSnake(root, cfg, hi) {
    if (!window.EventWorkflowSnake) {
      root.textContent = 'event-workflow-snake.js 未加载';
      return;
    }
    EventWorkflowSnake.renderLine(root, cfg, activeLine);
    highlightSnake(root, hi);
  }

  async function render(root, highlightRouteIds) {
    if (!root) return;
    root.classList.add('is-loading');
    root.textContent = '正在加载事件架构…';
    const cfg = await loadRoutesJson();
    if (!cfg && viewMode === 'snake') {
      root.textContent = '未加载 six_line_event_routes.json';
      return;
    }
    lastCfg = cfg;
    const hi = normalizeHi(highlightRouteIds);

    if (viewMode === 'merged') {
      await renderMerged(root, hi);
    } else if (cfg) {
      await renderSnake(root, cfg, hi);
    }

    bindTabs(root, cfg, hi);
  }

  function setActiveLine(lineId) {
    activeLine = lineId || activeLine;
  }

  function bindTabs(root, cfg, hi) {
    if (tabsBound) return;
    tabsBound = true;

    document.querySelectorAll('[data-event-view]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const mode = btn.getAttribute('data-event-view');
        viewMode = mode === 'detail' ? 'snake' : 'merged';
        document.querySelectorAll('[data-event-view]').forEach((b) => {
          const on = b === btn;
          b.classList.toggle('active', on);
          b.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        const lineTabs = document.querySelector('.event-line-tabs');
        if (lineTabs) lineTabs.hidden = viewMode !== 'snake';
        render(root, hi);
      });
    });

    if (window.EventWorkflowSnake) {
      EventWorkflowSnake.bindLineTabs(cfg, (lineId) => {
        activeLine = lineId;
        if (viewMode === 'snake' && lastCfg) {
          EventWorkflowSnake.renderLine(root, lastCfg, lineId);
          highlightSnake(root, hi);
        }
      });
    }
  }

  return { render, loadRoutesJson, setActiveLine };
})();

window.EventArchGraph = EventArchGraph;
