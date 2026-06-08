/**
 * 监控 Tab · 4 块 Grafana 卡片 live 渲染
 * 优先 Grafana render PNG（同源 /grafana/* 反代）；回退 Prometheus instant + range
 */
(function () {
  'use strict';

  const api = (path) => (window.XCAGIApi && window.XCAGIApi.url(path)) || path;
  const GRAF = api('/grafana');
  const PROM = api('/prometheus');
  const METRICS = api('/metrics');
  const JOB = 'xcagi-backend';

  const DASHES = [
    {
      id: 'api',
      uid: 'xcagi-api-overview',
      panelIds: [1, 2, 3, 4],
      prom: [
        {
          title: 'API 延迟 P95',
          expr: `histogram_quantile(0.95, sum by (le) (rate(api_request_duration_seconds_bucket{job="${JOB}"}[5m]))) * 1000`,
          unit: 'ms',
          cls: 'c',
          fmt: (v) => (v == null ? '—' : Math.round(v)),
        },
        {
          title: '请求量 / 秒',
          expr: `sum(rate(api_requests_total{job="${JOB}"}[1m]))`,
          unit: '次/秒',
          cls: 'b',
          fmt: (v) => (v == null ? '—' : v < 10 ? v.toFixed(2) : Math.round(v)),
        },
        {
          title: '5xx 错误率',
          expr: `sum(rate(api_requests_total{job="${JOB}",status=~"5.."}[5m])) / clamp_min(sum(rate(api_requests_total{job="${JOB}"}[5m])), 1) * 100`,
          unit: '%',
          cls: 'g',
          fmt: (v) => (v == null ? '—' : v.toFixed(2)),
        },
        {
          title: '活跃请求',
          expr: 'sum(active_requests)',
          unit: '个',
          cls: 'o',
          fmt: (v) => (v == null ? '—' : Math.round(v)),
        },
      ],
    },
    {
      id: 'infra',
      uid: 'xcagi-infrastructure',
      panelIds: [1, 2, 3, 4],
      k8sOnly: true,
      prom: [
        {
          title: 'Pod CPU',
          expr: 'sum(rate(container_cpu_usage_seconds_total{pod=~"xcagi.*",container!=""}[5m])) * 100',
          unit: '%',
          cls: 'c',
          fmt: (v) => (v == null ? '—' : v.toFixed(1)),
        },
        {
          title: 'Pod 内存',
          expr: 'sum(container_memory_usage_bytes{pod=~"xcagi.*",container!=""})',
          unit: 'GiB',
          cls: 'b',
          fmt: (v) => (v == null ? '—' : (v / 1024 / 1024 / 1024).toFixed(2)),
        },
        {
          title: '磁盘 /',
          expr: '100 * (1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}))',
          unit: '%',
          cls: 'y',
          fmt: (v) => (v == null ? '—' : v.toFixed(0)),
        },
        {
          title: 'Pod 重启 1h',
          expr: 'sum(increase(kube_pod_container_status_restarts_total{pod=~"xcagi.*"}[1h]))',
          unit: '次',
          cls: 'g',
          fmt: (v) => (v == null ? '—' : Math.round(v)),
        },
      ],
    },
    {
      id: 'mod',
      uid: 'xcagi-mod-store',
      panelIds: [1, 5, 2, 4],
      prom: [
        {
          title: 'Mod 目录 QPS',
          expr: `sum(rate(api_requests_total{job="${JOB}",endpoint=~"/api/(mod-store|mods).*"}[1m]))`,
          unit: '次/秒',
          cls: 'c',
          fmt: (v) => (v == null ? '—' : v.toFixed(2)),
        },
        {
          title: 'SQLite 就绪率',
          expr: `sum(mod_sqlite_copy_present{job="${JOB}"}) / clamp_min(count(mod_sqlite_copy_present{job="${JOB}"}), 1) * 100`,
          unit: '%',
          cls: 'b',
          fmt: (v) => (v == null ? '—' : v.toFixed(0)),
        },
        {
          title: 'NeuroBus 投递率',
          expr: '100 * (1 - (sum(rate(neurobus_events_lost_total[5m])) + sum(rate(neurobus_events_dead_lettered_total[5m]))) / clamp_min(sum(rate(neurobus_events_published_total[5m])), 1))',
          unit: '%',
          cls: 'g',
          fmt: (v) => (v == null ? '—' : v.toFixed(2)),
        },
        {
          title: 'Mod API P95',
          expr: `histogram_quantile(0.95, sum by (le) (rate(api_request_duration_seconds_bucket{job="${JOB}",endpoint=~"/api/(mod-store|mods).*"}[5m]))) * 1000`,
          unit: 'ms',
          cls: 'p',
          fmt: (v) => (v == null ? '—' : Math.round(v)),
        },
      ],
    },
    {
      id: 'bus',
      uid: 'xcagi-neurobus',
      panelIds: [1, 2, 4, 3],
      prom: [
        {
          title: '发布 / 秒',
          expr: 'sum(rate(neurobus_events_published_total[1m]))',
          unit: '条/秒',
          cls: 'c',
          fmt: (v) => (v == null ? '—' : v < 10 ? v.toFixed(2) : Math.round(v)),
        },
        {
          title: '丢失+DLQ 5m',
          expr: 'sum(increase(neurobus_events_lost_total[5m])) + sum(increase(neurobus_events_dead_lettered_total[5m]))',
          unit: '条',
          cls: 'g',
          fmt: (v) => (v == null ? '—' : Math.round(v)),
        },
        {
          title: '断路器 OPEN',
          expr: 'max(circuit_breaker_state) or on() vector(0)',
          unit: '路',
          cls: 'g',
          fmt: (v) => (v == null ? '—' : Math.round(v)),
        },
        {
          title: 'AI 请求 P95',
          expr: `histogram_quantile(0.95, sum by (le) (rate(ai_request_duration_seconds_bucket{job="${JOB}"}[5m]))) * 1000`,
          unit: 'ms',
          cls: 'p',
          fmt: (v) => (v == null ? '—' : Math.round(v)),
        },
      ],
    },
  ];

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  }

  function setStatus(el, mode, text) {
    if (!el) return;
    el.classList.remove('live', 'prom', 'offline', 'k8s');
    el.classList.add(mode);
    el.textContent = text;
  }

  async function probe(url, timeoutMs) {
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const t = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
    try {
      const r = await fetch(url, ctrl ? { signal: ctrl.signal, cache: 'no-store' } : { cache: 'no-store' });
      return r.ok;
    } catch (_) {
      return false;
    } finally {
      if (t) clearTimeout(t);
    }
  }

  async function promInstant(expr) {
    const url = `${PROM}/api/v1/query?query=${encodeURIComponent(expr)}`;
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) return null;
    const ct = (r.headers.get('content-type') || '').toLowerCase();
    if (ct.includes('text/html')) return null;
    try {
      const j = await r.json();
      const res = j.data && j.data.result;
      if (!res || !res.length) return null;
      const v = parseFloat(res[0].value[1]);
      return Number.isFinite(v) ? v : null;
    } catch {
      return null;
    }
  }

  async function promRange(expr) {
    const end = Math.floor(Date.now() / 1000);
    const start = end - 900;
    const url =
      `${PROM}/api/v1/query_range?query=${encodeURIComponent(expr)}` +
      `&start=${start}&end=${end}&step=60`;
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) return [];
    const ct = (r.headers.get('content-type') || '').toLowerCase();
    if (ct.includes('text/html')) return [];
    try {
      const j = await r.json();
      const series = j.data && j.data.result && j.data.result[0];
      if (!series || !series.values) return [];
      return series.values.map((p) => parseFloat(p[1])).filter((n) => Number.isFinite(n));
    } catch {
      return [];
    }
  }

  function sparklineSvg(values, stroke) {
    if (!values.length) {
      return '<svg viewBox="0 0 100 30" preserveAspectRatio="none"><path d="M0,15 L100,15" fill="none" stroke="#484f58" stroke-width="1" stroke-dasharray="3 3"/></svg>';
    }
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const pts = values.map((v, i) => {
      const x = (i / Math.max(values.length - 1, 1)) * 100;
      const y = 28 - ((v - min) / span) * 24;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const line = 'M' + pts.join(' L');
    const area = line + ' L100,30 L0,30 Z';
    const gid = 'sg' + Math.random().toString(36).slice(2, 8);
    return (
      `<svg viewBox="0 0 100 30" preserveAspectRatio="none">` +
      `<defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1">` +
      `<stop offset="0" stop-color="${stroke}" stop-opacity=".35"/>` +
      `<stop offset="1" stop-color="${stroke}" stop-opacity="0"/></linearGradient></defs>` +
      `<path d="${area}" fill="url(#${gid})"/>` +
      `<path d="${line}" fill="none" stroke="${stroke}" stroke-width="1.2"/></svg>`
    );
  }

  const strokeMap = { c: '#58e2c2', g: '#56d364', b: '#79c0ff', o: '#ffa657', p: '#d2a8ff', y: '#e3b341' };

  /** Grafana render 较慢（16 面板 ≈ 30s）；60s 轮询避免重叠请求 */
  const REFRESH_MS = 60_000;
  let refreshTimer = null;

  function isMonitorActive() {
    return document.getElementById('s-monitor')?.classList.contains('active');
  }

  function liveStatusLabel(text) {
    const t = new Date();
    const stamp = `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`;
    return `${text} · ${stamp}`;
  }

  function revokePanelBlobUrls(panel) {
    panel.querySelectorAll('.mon-grafana-panel-img').forEach((img) => {
      const src = img.getAttribute('src') || '';
      if (src.startsWith('blob:')) URL.revokeObjectURL(src);
    });
  }

  function stopRefreshLoop() {
    if (refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    }
  }

  function startRefreshLoop() {
    stopRefreshLoop();
    refreshTimer = setInterval(() => {
      if (isMonitorActive() && !document.hidden) refreshAll({ silent: true });
    }, REFRESH_MS);
  }

  function browserTz() {
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      return tz && tz !== 'browser' ? tz : 'UTC';
    } catch (_) {
      return 'UTC';
    }
  }

  async function isImageBlob(blob) {
    if (blob.type && blob.type.startsWith('image/')) return true;
    const head = new Uint8Array(await blob.slice(0, 8).arrayBuffer());
    return head[0] === 0x89 && head[1] === 0x50 && head[2] === 0x4e && head[3] === 0x47;
  }

  async function grafanaPanelBlob(uid, panelId) {
    const q =
      `/render/d-solo/${uid}?orgId=1&panelId=${panelId}` +
      `&width=420&height=180&from=now-15m&to=now&tz=${encodeURIComponent(browserTz())}`;
    const r = await fetch(`${GRAF}${q}`, { cache: 'no-store' });
    if (!r.ok) return null;
    const ct = (r.headers.get('content-type') || '').toLowerCase();
    if (ct.includes('text/html')) return null;
    const blob = await r.blob();
    if (!blob.size) return null;
    if (!(await isImageBlob(blob))) return null;
    return URL.createObjectURL(blob);
  }

  async function renderGrafanaCard(card, spec) {
    const panels = card.querySelectorAll('.mon-mini-panel');
    let ok = 0;
    for (let i = 0; i < spec.panelIds.length && i < panels.length; i++) {
      const blobUrl = await grafanaPanelBlob(spec.uid, spec.panelIds[i]);
      if (!blobUrl) continue;
      revokePanelBlobUrls(panels[i]);
      panels[i].classList.add('mon-live-grafana');
      panels[i].innerHTML =
        `<img class="mon-grafana-panel-img" src="${esc(blobUrl)}" alt="${esc(spec.uid)}:${spec.panelIds[i]}" />`;
      ok++;
    }
    return ok;
  }

  async function renderPromCard(card, spec) {
    const panels = card.querySelectorAll('.mon-mini-panel');
    let ok = 0;
    for (let i = 0; i < spec.prom.length && i < panels.length; i++) {
      const p = spec.prom[i];
      let val = null;
      try {
        val = await promInstant(p.expr);
      } catch (_) { /* offline */ }
      const numEl = panels[i].querySelector('.mon-mini-panel-num');
      const titleEl = panels[i].querySelector('.mon-mini-panel-title');
      const unitEl = panels[i].querySelector('.mon-mini-panel-unit');
      const chartEl = panels[i].querySelector('.mon-mini-chart');
      if (titleEl) titleEl.textContent = p.title;
      if (numEl) {
        numEl.textContent = p.fmt(val);
        numEl.className = 'mon-mini-panel-num ' + p.cls;
      }
      if (unitEl) unitEl.textContent = p.unit;
      let series = [];
      try {
        series = await promRange(p.expr);
      } catch (_) { /* offline */ }
      if (chartEl) chartEl.innerHTML = sparklineSvg(series, strokeMap[p.cls] || '#58e2c2');
      if (val != null) ok++;
    }
    return ok;
  }

  async function renderMetricsFallback(card, spec) {
    let text = '';
    try {
      const r = await fetch(METRICS, { cache: 'no-store' });
      if (r.ok) text = await r.text();
    } catch (_) {
      return 0;
    }
    if (!text) return 0;
    const panels = card.querySelectorAll('.mon-mini-panel');
    let ok = 0;
    if (spec.id === 'api') {
      const total = matchMetricSum(text, 'api_requests_total');
      const err = matchMetricSum(text, 'api_requests_total', (l) => /status="5/.test(l));
      if (total > 0 && panels[2]) {
        const rate = ((total - err) / total) * 100;
        setMini(panels[2], '可用率', rate.toFixed(2), '%', 'g');
        ok++;
      }
    }
    if (spec.id === 'mod') {
      const ready = matchMetricSum(text, 'mod_sqlite_copy_present', (l) => /}\s+1(\.0)?$/.test(l));
      if (ready > 0 && panels[1]) {
        setMini(panels[1], 'SQLite 副本就绪', String(Math.round(ready)), '个', 'b');
        ok++;
      }
      const pub = matchMetricSum(text, 'neurobus_events_published_total');
      if (pub > 0 && panels[2]) {
        setMini(panels[2], 'NeuroBus 已发布', String(Math.round(pub)), '累计', 'g');
        ok++;
      }
    }
    return ok;
  }

  function matchMetricSum(text, name, filterFn) {
    let sum = 0;
    const re = new RegExp('^' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\{[^}]*\\})?\\s+(\\S+)', 'gm');
    let m;
    while ((m = re.exec(text))) {
      const line = m[0];
      if (filterFn && !filterFn(line)) continue;
      sum += parseFloat(m[2]) || 0;
    }
    return sum;
  }

  function setMini(panel, title, num, unit, cls) {
    const titleEl = panel.querySelector('.mon-mini-panel-title');
    const numEl = panel.querySelector('.mon-mini-panel-num');
    const unitEl = panel.querySelector('.mon-mini-panel-unit');
    if (titleEl) titleEl.textContent = title;
    if (numEl) {
      numEl.textContent = num;
      numEl.className = 'mon-mini-panel-num ' + cls;
    }
    if (unitEl) unitEl.textContent = unit;
  }

  async function refreshCard(card, spec, opts) {
    const silent = !!(opts && opts.silent);
    const statusEl = card.querySelector('.mon-dash-status');
    if (!silent) setStatus(statusEl, 'offline', '加载中…');

    const grafanaUp = await probe(`${GRAF}/api/health`, 2500);
    if (grafanaUp) {
      const n = await renderGrafanaCard(card, spec);
      if (n >= 2) {
        setStatus(statusEl, 'live', liveStatusLabel('Grafana live'));
        return true;
      }
    }

    const promUp = await probe(`${PROM}/api/v1/query?query=up`, 2500);
    if (promUp) {
      const n = await renderPromCard(card, spec);
      if (n >= 1) {
        setStatus(statusEl, 'prom', liveStatusLabel('Prometheus'));
        return true;
      }
      if (spec.k8sOnly) {
        if (!silent) setStatus(statusEl, 'k8s', '需 K8s');
        return false;
      }
    }

    const n = await renderMetricsFallback(card, spec);
    if (n >= 1) {
      setStatus(statusEl, 'prom', liveStatusLabel('/metrics'));
      return true;
    }
    if (!silent) setStatus(statusEl, 'offline', '无数据 · 起栈');
    return false;
  }

  async function refreshAll(opts) {
    const cards = document.querySelectorAll('.mon-dash-grid .mon-dash-card[data-mon-dash]');
    const map = {};
    DASHES.forEach((d) => {
      map[d.id] = d;
    });
    cards.forEach((card) => {
      const id = card.getAttribute('data-mon-dash');
      const spec = map[id];
      if (spec) refreshCard(card, spec, opts);
    });
    const note = document.getElementById('mon-dash-live-note');
    if (note) {
      note.textContent = ` · 每 ${REFRESH_MS / 1000}s 自动刷新 · Grafana render 回退 Prometheus /metrics`;
    }
  }

  function onMonitorTab() {
    refreshAll();
    startRefreshLoop();
  }

  document.addEventListener('xcagi-tab-shown', (ev) => {
    if (ev.detail && ev.detail.tab === 'monitor') onMonitorTab();
    else stopRefreshLoop();
  });

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    if (isMonitorActive()) refreshAll({ silent: true });
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      if (document.getElementById('s-monitor')?.classList.contains('active')) onMonitorTab();
    });
  } else if (document.getElementById('s-monitor')?.classList.contains('active')) {
    onMonitorTab();
  }

  window.MonLiveDash = { refreshAll, startRefreshLoop, stopRefreshLoop };
})();
