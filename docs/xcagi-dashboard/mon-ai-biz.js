/**
 * AI 业务数据 Tab · Token / 请求量 / 模型目录
 * 优先 Prometheus instant + range；回退 /metrics 文本解析
 */
(function () {
  'use strict';

  const api = (path) => (window.XCAGIApi && window.XCAGIApi.url(path)) || path;
  const PROM = api('/prometheus');
  const METRICS = api('/metrics');
  const JOB = 'xcagi-backend';

  const KPI = [
    {
      id: 'ai-qps',
      title: 'AI 请求 / 秒',
      expr: `sum(rate(ai_requests_total{job="${JOB}"}[1m]))`,
      unit: '次/秒',
      cls: 'c',
      fmt: (v) => (v == null ? '—' : v < 10 ? v.toFixed(2) : Math.round(v)),
      rangeExpr: `sum(rate(ai_requests_total{job="${JOB}"}[1m]))`,
    },
    {
      id: 'ai-err',
      title: 'AI 错误率',
      expr: `sum(rate(ai_request_errors_total{job="${JOB}"}[5m])) / clamp_min(sum(rate(ai_requests_total{job="${JOB}"}[5m])), 1) * 100`,
      unit: '%',
      cls: 'g',
      fmt: (v) => (v == null ? '—' : v.toFixed(2)),
      rangeExpr: `sum(rate(ai_request_errors_total{job="${JOB}"}[5m])) / clamp_min(sum(rate(ai_requests_total{job="${JOB}"}[5m])), 1) * 100`,
    },
    {
      id: 'ai-ttft',
      title: '聊天首字 P95',
      expr: `histogram_quantile(0.95, sum by (le) (rate(chat_stream_first_byte_seconds_bucket{job="${JOB}"}[5m]))) * 1000`,
      unit: 'ms',
      cls: 'p',
      fmt: (v) => (v == null ? '—' : Math.round(v)),
      rangeExpr: `histogram_quantile(0.95, sum by (le) (rate(chat_stream_first_byte_seconds_bucket{job="${JOB}"}[5m]))) * 1000`,
    },
    {
      id: 'ai-lat',
      title: 'AI 延迟 P95',
      expr: `histogram_quantile(0.95, sum by (le) (rate(ai_request_duration_seconds_bucket{job="${JOB}"}[5m]))) * 1000`,
      unit: 'ms',
      cls: 'b',
      fmt: (v) => (v == null ? '—' : Math.round(v)),
      rangeExpr: `histogram_quantile(0.95, sum by (le) (rate(ai_request_duration_seconds_bucket{job="${JOB}"}[5m]))) * 1000`,
    },
  ];

  const TOKEN_KPI = [
    {
      id: 'ai-req-24h',
      title: '24h 累计 AI 请求',
      expr: `sum(increase(ai_requests_total{job="${JOB}"}[24h]))`,
      unit: '次',
      cls: 'o',
      fmt: (v) => (v == null ? '—' : Math.round(v)),
    },
    {
      id: 'ai-req-total',
      title: '累计 AI 请求',
      expr: `sum(ai_requests_total{job="${JOB}"})`,
      unit: '次',
      cls: 'y',
      fmt: (v) => (v == null ? '—' : Math.round(v)),
    },
  ];

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  }

  // 三端展示 mockup 的数字滚动动画（展示性 / 动画性）
  function animateCounters(force) {
    const reduce =
      window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const els = document.querySelectorAll('#aibiz-triple-grid .k-num[data-count]');
    els.forEach((el) => {
      if (el.dataset.animated && !force) return;
      el.dataset.animated = '1';
      const target = parseFloat(el.dataset.count) || 0;
      const dec = parseInt(el.dataset.dec || '0', 10);
      const prefix = el.dataset.prefix || '';
      const suffix = el.dataset.suffix || '';
      const paint = (v) =>
        (el.textContent =
          prefix + (dec ? v.toFixed(dec) : Math.round(v).toLocaleString()) + suffix);
      if (reduce) {
        paint(target);
        return;
      }
      const dur = 1100;
      const t0 = performance.now();
      const step = (now) => {
        const t = Math.min(1, (now - t0) / dur);
        paint(target * (1 - Math.pow(1 - t, 3)));
        if (t < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
  }

  function setLiveStatus(mode, text) {
    const el = document.getElementById('aibiz-live-status');
    if (!el) return;
    el.classList.remove('live', 'prom', 'offline');
    if (mode) el.classList.add(mode);
    el.textContent = text;
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
    const gid = 'aibiz' + Math.random().toString(36).slice(2, 8);
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

  async function probeProm() {
    try {
      const r = await fetch(`${PROM}/api/v1/query?query=up`, { cache: 'no-store' });
      return r.ok;
    } catch (_) {
      return false;
    }
  }

  async function metricsCounter(name) {
    try {
      const r = await fetch(METRICS, { cache: 'no-store' });
      if (!r.ok) return null;
      const text = await r.text();
      const re = new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(\\{[^}]*\\})?\\s+([0-9.eE+-]+)`, 'gm');
      let sum = 0;
      let m;
      while ((m = re.exec(text)) !== null) {
        const v = parseFloat(m[2]);
        if (Number.isFinite(v)) sum += v;
      }
      return sum > 0 ? sum : null;
    } catch (_) {
      return null;
    }
  }

  async function renderKpiCard(card, spec, useProm) {
    const numEl = card.querySelector('.aibiz-kpi-num');
    const unitEl = card.querySelector('.aibiz-kpi-unit');
    const sparkEl = card.querySelector('.aibiz-kpi-spark');
    let val = null;
    let series = [];

    if (useProm) {
      try {
        val = await promInstant(spec.expr);
        if (spec.rangeExpr) series = await promRange(spec.rangeExpr);
      } catch (_) { /* offline */ }
    }
    if (val == null && spec.fallbackMetric) {
      val = await metricsCounter(spec.fallbackMetric);
    }

    if (numEl) {
      numEl.className = 'aibiz-kpi-num ' + (spec.cls || 'c');
      numEl.textContent = spec.fmt(val);
    }
    if (unitEl) unitEl.textContent = spec.unit || '';
    if (sparkEl) sparkEl.innerHTML = sparklineSvg(series, strokeMap[spec.cls] || strokeMap.c);
    return val != null;
  }

  async function refreshKpis() {
    const promUp = await probeProm();
    const cards = document.querySelectorAll('#aibiz-kpi-grid .aibiz-kpi-card');
    const specs = [...KPI, ...TOKEN_KPI];
    let ok = 0;
    for (let i = 0; i < cards.length && i < specs.length; i++) {
      const hit = await renderKpiCard(cards[i], specs[i], promUp);
      if (hit) ok++;
    }

    if (promUp && ok >= 2) setLiveStatus('live', 'Prometheus live · ' + new Date().toLocaleTimeString());
    else if (ok >= 1) setLiveStatus('prom', '/metrics 回退 · ' + new Date().toLocaleTimeString());
    else setLiveStatus('offline', '无数据 · 请起 bash scripts/serve_xcagi_dashboard.sh + FHD（:5100/:5000）后产生一次 AI 请求');

    const note = document.getElementById('aibiz-live-note');
    if (note) {
      note.textContent = promUp
        ? '指标来自 Prometheus（ai_requests_total / ai_request_errors_total / chat_stream_first_byte_seconds / ai_request_duration_seconds）'
        : 'Prometheus 不可达，已尝试 /metrics 文本解析';
    }
  }

  async function refreshByService() {
    const tbody = document.getElementById('aibiz-service-body');
    if (!tbody) return;
    const promUp = await probeProm();
    if (!promUp) {
      tbody.innerHTML =
        '<tr><td colspan="4" class="aibiz-empty">Prometheus 离线 · 启动本地栈后可按 service 维度拆分</td></tr>';
      return;
    }
    const expr = `sum by (service, status) (rate(ai_requests_total{job="${JOB}"}[5m]))`;
    try {
      const url = `${PROM}/api/v1/query?query=${encodeURIComponent(expr)}`;
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) throw new Error('query failed');
      const j = await r.json();
      const rows = (j.data && j.data.result) || [];
      if (!rows.length) {
        tbody.innerHTML =
          '<tr><td colspan="4" class="aibiz-empty">暂无 ai_requests_total 时序 · 发起几次 /api/llm/chat 后刷新</td></tr>';
        return;
      }
      const map = {};
      rows.forEach((item) => {
        const svc = item.metric.service || 'unknown';
        const st = item.metric.status || 'unknown';
        const v = parseFloat(item.value[1]);
        if (!map[svc]) map[svc] = { success: 0, error: 0 };
        if (st === 'success') map[svc].success += v;
        else map[svc].error += v;
      });
      const html = Object.keys(map)
        .sort()
        .map((svc) => {
          const s = map[svc];
          const total = s.success + s.error;
          const errPct = total > 0 ? ((s.error / total) * 100).toFixed(2) : '0.00';
          return (
            `<tr><td><code>${esc(svc)}</code></td>` +
            `<td>${s.success < 0.01 ? s.success.toFixed(3) : s.success.toFixed(2)}</td>` +
            `<td>${s.error < 0.01 ? s.error.toFixed(3) : s.error.toFixed(2)}</td>` +
            `<td>${errPct}%</td></tr>`
          );
        })
        .join('');
      tbody.innerHTML = html;
    } catch (_) {
      tbody.innerHTML = '<tr><td colspan="4" class="aibiz-empty">查询失败</td></tr>';
    }
  }

  const surfaceCacheByTerminal = { web: null, software: null, app: null };

  const TERMINAL_GALLERY = {
    web: {
      title: 'P-W 网站 · xiu-ci.com 全部网页',
      sub: 'SW · 营销静态 + AI 市场 Tab · 1280×720',
      api: '/api/xcmax/aibiz/web-terminal',
    },
    software: {
      title: 'P-S 软件 · 本地企业版',
      sub: 'SS · FHD 桌面 · enterprise SKU · 127.0.0.1:5001 · 演示账号 xcagi-enterprise-demo',
      api: '/api/xcmax/aibiz/desk-terminal',
    },
    app: {
      title: 'P-App 移动 · 企业版',
      sub: 'SA · enterprise SKU · adb 真机 + WebView · 演示账号 xcagi-enterprise-demo',
      api: '/api/xcmax/aibiz/app-terminal',
    },
  };

  let screenshotGallery = { list: [], index: 0, terminal: 'web', animating: false };
  const screenshotImageCache = new Map();
  const terminalFetchControllers = {};

  function surfaceImgSrc(terminal, index, page, view) {
    const wantViewport = view === 'viewport' || (view !== 'thumb' && terminal === 'web' && terminal !== 'app');
    if (page && page.preview_image_url && wantViewport) {
      const u = page.preview_image_url
      return u.startsWith('http') ? u : api(u)
    }
    if (page && page.image_url) {
      let u = page.image_url
      if (view === 'thumb') {
        u += (u.indexOf('?') >= 0 ? '&' : '?') + 'view=thumb'
      } else if (wantViewport && u.indexOf('view=') < 0) {
        u += (u.indexOf('?') >= 0 ? '&' : '?') + 'view=viewport'
      }
      return u.startsWith('http') ? u : api(u)
    }
    if (page && page.screenshot_b64 && view !== 'thumb') {
      return `data:image/png;base64,${page.screenshot_b64}`
    }
    let path = `/api/xcmax/aibiz/surface-image?terminal=${encodeURIComponent(terminal)}&index=${index}`
    if (view === 'thumb') path += '&view=thumb'
    else if (wantViewport) path += '&view=viewport'
    return api(path)
  }

  function normalizeScreenshotIndex(index, len) {
    return ((index % len) + len) % len;
  }

  function screenshotPrefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function preloadScreenshotImage(terminal, index, page) {
    const src = surfaceImgSrc(terminal, index, page);
    if (screenshotImageCache.has(src)) return screenshotImageCache.get(src);
    const promise = new Promise((resolve) => {
      const img = new Image();
      img.decoding = 'async';
      img.onload = () => resolve({ img, src, ok: true });
      img.onerror = () => resolve({ img: null, src, ok: false });
      img.src = src;
    });
    screenshotImageCache.set(src, promise);
    return promise;
  }

  function preloadScreenshotNeighbors(centerIdx) {
    const list = screenshotGallery.list;
    const terminal = screenshotGallery.terminal;
    if (!list.length || list.length <= 1) return;
    const len = list.length;
    const prev = normalizeScreenshotIndex(centerIdx - 1, len);
    const next = normalizeScreenshotIndex(centerIdx + 1, len);
    preloadScreenshotImage(terminal, prev, list[prev]);
    preloadScreenshotImage(terminal, next, list[next]);
  }

  function slideLabel(page) {
    return page.name || page.url || '页面截图';
  }

  function paintScreenshotSlide(slideEl, loaded, page) {
    const label = slideLabel(page);
    if (loaded?.ok && loaded.img) {
      const img = loaded.img.cloneNode(true);
      img.className = 'aibiz-screenshot-img';
      img.alt = label;
      img.decoding = 'async';
      slideEl.replaceChildren(img);
      return;
    }
    if (loaded?.ok === false) {
      slideEl.innerHTML = `<div class="aibiz-screenshot-empty">截图加载失败 · ${esc(label)}</div>`;
      return;
    }
    slideEl.innerHTML = '<div class="aibiz-screenshot-loading">加载截图…</div>';
  }

  function updateScreenshotChrome(i, page, list, modal) {
    const label = page.name || page.url || '页面截图';
    const caption = document.getElementById('aibiz-screenshot-caption');
    const counter = document.getElementById('aibiz-screenshot-counter');
    if (caption) caption.textContent = label;
    if (counter) counter.textContent = `${i + 1} / ${list.length}`;
    if (modal) {
      const disabled = list.length <= 1;
      const prev = modal.querySelector('[data-aibiz-shot-prev]');
      const next = modal.querySelector('[data-aibiz-shot-next]');
      if (prev) prev.disabled = disabled;
      if (next) next.disabled = disabled;
    }
  }

  function ensureScreenshotViewport(body) {
    let viewport = body.querySelector('.aibiz-screenshot-viewport');
    if (!viewport) {
      body.replaceChildren();
      viewport = document.createElement('div');
      viewport.className = 'aibiz-screenshot-viewport';
      const track = document.createElement('div');
      track.className = 'aibiz-screenshot-track';
      viewport.appendChild(track);
      body.appendChild(viewport);
    }
    let track = viewport.querySelector('.aibiz-screenshot-track');
    if (!track) {
      track = document.createElement('div');
      track.className = 'aibiz-screenshot-track';
      viewport.appendChild(track);
    }
    return { viewport, track };
  }

  function fillScreenshotSlide(slideEl, index, page) {
    slideEl.innerHTML = '<div class="aibiz-screenshot-loading">加载截图…</div>';
    preloadScreenshotImage(screenshotGallery.terminal, index, page).then((loaded) => {
      paintScreenshotSlide(slideEl, loaded, page);
    });
  }

  function mountStaticScreenshotSlide(body, index, page) {
    const { track } = ensureScreenshotViewport(body);
    track.className = 'aibiz-screenshot-track';
    track.style.width = '';
    track.style.transform = 'translate3d(0,0,0)';
    track.style.transition = '';
    track.classList.remove('is-sliding');
    track.replaceChildren();
    const slide = document.createElement('div');
    slide.className = 'aibiz-screenshot-slide';
    track.appendChild(slide);
    preloadScreenshotImage(screenshotGallery.terminal, index, page).then((loaded) => {
      paintScreenshotSlide(slide, loaded, page);
      preloadScreenshotNeighbors(index);
    });
  }

  function snapScreenshotTrack(track, targetSlide) {
    track.classList.remove('is-sliding');
    track.style.transition = 'none';
    track.replaceChildren(targetSlide);
    track.className = 'aibiz-screenshot-track';
    track.style.width = '';
    track.style.transform = 'translate3d(0,0,0)';
    void track.offsetWidth;
    track.style.transition = '';
  }

  async function renderScreenshotSlide(index, direction) {
    const body = document.getElementById('aibiz-screenshot-body');
    const modal = document.getElementById('aibiz-screenshot-modal');
    const list = screenshotGallery.list;
    const terminal = screenshotGallery.terminal;
    if (!body || !list.length) return;
    if (screenshotGallery.animating) return;

    const i = normalizeScreenshotIndex(index, list.length);
    const page = list[i];
    const delta = direction || 0;
    const fromIdx = screenshotGallery.index;
    const canAnimate =
      delta !== 0 &&
      list.length > 1 &&
      i !== fromIdx &&
      !screenshotPrefersReducedMotion();

    if (!canAnimate) {
      screenshotGallery.index = i;
      updateScreenshotChrome(i, page, list, modal);
      mountStaticScreenshotSlide(body, i, page);
      return;
    }

    screenshotGallery.animating = true;
    updateScreenshotChrome(i, page, list, modal);
    modal?.querySelectorAll('[data-aibiz-shot-prev], [data-aibiz-shot-next]').forEach((btn) => {
      btn.disabled = true;
    });

    const fromPage = list[fromIdx];
    const [fromLoaded, toLoaded] = await Promise.all([
      preloadScreenshotImage(terminal, fromIdx, fromPage),
      preloadScreenshotImage(terminal, i, page),
    ]);

    const { track } = ensureScreenshotViewport(body);
    const dir = delta > 0 ? 1 : -1;
    track.className = 'aibiz-screenshot-track aibiz-screenshot-track--marquee';
    track.classList.remove('is-sliding');
    track.style.transition = 'none';
    track.replaceChildren();

    const fromSlide = document.createElement('div');
    fromSlide.className = 'aibiz-screenshot-slide';
    const toSlide = document.createElement('div');
    toSlide.className = 'aibiz-screenshot-slide';
    paintScreenshotSlide(fromSlide, fromLoaded, fromPage);
    paintScreenshotSlide(toSlide, toLoaded, page);

    const finish = () => {
      if (!screenshotGallery.animating) return;
      snapScreenshotTrack(track, toSlide);
      screenshotGallery.index = i;
      screenshotGallery.animating = false;
      updateScreenshotChrome(i, page, list, modal);
      preloadScreenshotNeighbors(i);
    };

    if (dir > 0) {
      track.append(fromSlide, toSlide);
      track.style.transform = 'translate3d(0,0,0)';
    } else {
      track.append(toSlide, fromSlide);
      track.style.transform = 'translate3d(-100%,0,0)';
    }
    void track.offsetWidth;

    requestAnimationFrame(() => {
      track.classList.add('is-sliding');
      track.style.transition = '';
      track.style.transform = dir > 0 ? 'translate3d(-100%,0,0)' : 'translate3d(0,0,0)';
    });

    let done = false;
    const onEnd = (ev) => {
      if (ev.target !== track || ev.propertyName !== 'transform') return;
      if (done) return;
      done = true;
      track.removeEventListener('transitionend', onEnd);
      finish();
    };
    track.addEventListener('transitionend', onEnd);
    window.setTimeout(() => {
      if (done) return;
      done = true;
      track.removeEventListener('transitionend', onEnd);
      finish();
    }, 620);
  }

  function stepScreenshotGallery(delta) {
    renderScreenshotSlide(screenshotGallery.index + delta, delta);
  }

  function ensureScreenshotModal() {
    let modal = document.getElementById('aibiz-screenshot-modal');
    if (modal && (modal.querySelector('.aibiz-screenshot-head') || !modal.querySelector('[data-aibiz-shot-prev]'))) {
      modal.remove();
      modal = null;
    }
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'aibiz-screenshot-modal';
    modal.className = 'aibiz-screenshot-modal';
    modal.hidden = true;
    modal.innerHTML =
      '<div class="aibiz-screenshot-backdrop" data-aibiz-screenshot-close></div>' +
      '<div class="aibiz-screenshot-dialog" role="dialog" aria-modal="true" aria-label="页面截图">' +
      '<button type="button" class="aibiz-screenshot-close" data-aibiz-screenshot-close aria-label="关闭">×</button>' +
      '<button type="button" class="aibiz-screenshot-nav aibiz-screenshot-nav--prev" data-aibiz-shot-prev aria-label="上一页">‹</button>' +
      '<div class="aibiz-screenshot-body" id="aibiz-screenshot-body"></div>' +
      '<button type="button" class="aibiz-screenshot-nav aibiz-screenshot-nav--next" data-aibiz-shot-next aria-label="下一页">›</button>' +
      '<span class="aibiz-screenshot-counter" id="aibiz-screenshot-counter">1 / 1</span>' +
      '<span class="aibiz-screenshot-caption" id="aibiz-screenshot-caption"></span>' +
      '<span id="aibiz-screenshot-title" hidden></span>' +
      '<span id="aibiz-screenshot-sub" hidden></span>' +
      '</div>';
    document.body.appendChild(modal);
    modal.querySelectorAll('[data-aibiz-screenshot-close]').forEach((el) => {
      el.addEventListener('click', closeWebScreenshotGallery);
    });
    modal.querySelector('[data-aibiz-shot-prev]')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      stepScreenshotGallery(-1);
    });
    modal.querySelector('[data-aibiz-shot-next]')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      stepScreenshotGallery(1);
    });
    document.addEventListener('keydown', (ev) => {
      const m = document.getElementById('aibiz-screenshot-modal');
      if (!m || m.hidden) return;
      if (ev.key === 'Escape') closeWebScreenshotGallery();
      if (ev.key === 'ArrowLeft') {
        ev.preventDefault();
        stepScreenshotGallery(-1);
      }
      if (ev.key === 'ArrowRight') {
        ev.preventDefault();
        stepScreenshotGallery(1);
      }
    });
    return modal;
  }

  function closeWebScreenshotGallery() {
    const modal = document.getElementById('aibiz-screenshot-modal');
    if (!modal) return;
    modal.hidden = true;
    screenshotGallery.animating = false;
    document.body.classList.remove('aibiz-screenshot-open');
  }

  function terminalApiQuery(refresh, compact) {
    const q = [];
    if (refresh) q.push('refresh=1');
    if (compact === false) q.push('compact=0');
    return q.length ? '?' + q.join('&') : '';
  }

  function terminalLoadingHtml(terminal, refresh) {
    const lane =
      terminal === 'web' ? 'P-W 网站' : terminal === 'software' ? 'P-S 软件' : 'P-App 移动';
    let pipeline;
    if (refresh) {
      pipeline =
        terminal === 'app'
          ? '正在触发 FHD 本地巡检（企业版 App · adb + Playwright，约 30–90 秒）…'
          : '正在触发 surface-audit 巡检（Playwright，约 10–30 秒）…';
    } else if (terminal === 'app') {
      pipeline = '正在读取 FHD 本地<strong>企业版 App</strong>截图（enterprise SKU · adb / 缓存）…';
    } else if (terminal === 'software') {
      pipeline = '正在读取 FHD 本地<strong>企业版客户端</strong>截图（企业账号 · 127.0.0.1:5001）…';
    } else {
      pipeline =
        '正在从 xiu-ci.com 读取<strong>全部网页</strong>截图（PNG 直链）…';
    }
    return (
      `<div class="aibiz-terminal-live-empty aibiz-terminal-live-loading">` +
      `<div class="aibiz-terminal-live-title">正在加载 ${esc(lane)} 截图</div>` +
      `<p>${pipeline}</p>` +
      `<p class="aibiz-terminal-live-hint">点终端打开画廊按页加载 PNG；↻ 才会重新 Playwright 巡检</p>` +
      `</div>`
    );
  }

  async function openTerminalScreenshotGallery(terminal, pages, startIndex) {
    const meta = TERMINAL_GALLERY[terminal] || TERMINAL_GALLERY.web;
    const list = Array.isArray(pages) ? pages.filter((p) => p && p.name) : [];
    const modal = ensureScreenshotModal();
    const title = document.getElementById('aibiz-screenshot-title');
    const body = document.getElementById('aibiz-screenshot-body');
    const sub = document.getElementById('aibiz-screenshot-sub');
    if (title) title.textContent = meta.title;
    if (!list.length) {
      body.innerHTML =
        '<div class="aibiz-screenshot-empty">暂无截图 · 请配置 <code>XCAGI_AIBIZ_MARKET_*</code> 后点 ↻ 触发巡检</div>';
      if (sub) sub.textContent = meta.sub;
    } else {
      const start = Math.min(Math.max(0, parseInt(startIndex, 10) || 0), list.length - 1);
      if (sub) sub.textContent = `${meta.sub} · ${list.length} 页 · ← → 翻页 · Esc 关闭`;
      screenshotGallery.list = list;
      screenshotGallery.terminal = terminal;
      screenshotGallery.index = start;
      modal.hidden = false;
      document.body.classList.add('aibiz-screenshot-open');
      await renderScreenshotSlide(start);
      return;
    }
    modal.hidden = false;
    document.body.classList.add('aibiz-screenshot-open');
  }

  function openWebScreenshotGallery(pages) {
    return openTerminalScreenshotGallery('web', pages);
  }

  function aibizDevHint(status) {
    const hint = (window.XCAGIApi && window.XCAGIApi.devServerHint) || '';
    if (status === 404) {
      return (
        `<p class="aibiz-terminal-live-hint">` +
        `<strong>404</strong>：当前页面所在端口没有 <code>/api</code> 反代，或 FHD :5000 仍是旧进程（无 aibiz 路由）。` +
        `<br/>① 终端1：<code>bash scripts/serve_xcagi_dashboard.sh</code>` +
        `<br/>② 终端2：重启 FHD（含 <code>XCAGI_AIBIZ_MARKET_*</code>）` +
        `<br/>③ 浏览器打开 <code>http://127.0.0.1:8765/XCAGI-Full-Pipeline.html</code>` +
        (hint ? `<br/>${esc(hint)}` : '') +
        `</p>`
      );
    }
    return (
      `<p class="aibiz-terminal-live-hint">配置 FHD <code>XCAGI_MARKET_BASE_URL=https://xiu-ci.com</code> · ` +
      `服务账号 <code>XCAGI_AIBIZ_MARKET_USER/PASSWORD</code>（管理员）</p>`
    );
  }

  async function refreshTerminal(terminal, apiPath, screenSel, badgeSel, refresh) {
    const screen = document.querySelector(screenSel);
    const badge = document.querySelector(badgeSel);
    if (!screen) return;
    if (terminalFetchControllers[terminal]) {
      terminalFetchControllers[terminal].abort();
    }
    const controller = new AbortController();
    terminalFetchControllers[terminal] = controller;
    const timer = setTimeout(() => controller.abort(), 90000);
    screen.classList.add('aibiz-terminal-screen--loading');
    if (badge) {
      badge.textContent = '加载中';
      badge.classList.remove('live', 'offline');
    }
    try {
      const r = await fetch(apiPath.startsWith('http') ? apiPath : api(apiPath), {
        cache: 'no-store',
        signal: controller.signal,
      });
      let j = {};
      try {
        j = await r.json();
      } catch (_) {
        j = {};
      }
      if (!r.ok || !j.success) {
        // 保留动画 mockup 作为展示占位，仅更新状态徽标（不擦除内容）
        const msg = (j && j.message) || `HTTP ${r.status}`;
        screen.setAttribute('title', '演示占位 · 接口未就绪：' + msg);
        if (badge) {
          badge.textContent = '演示';
          badge.classList.add('offline');
        }
        return;
      }
      const surface = (j.data && j.data.surface_audit) || {};
      const pages = Array.isArray(surface.pages) ? surface.pages : [];
      if (pages.length) {
        renderTerminalScreen(screen, j.data || {}, terminal);
        if (badge) {
          badge.textContent = '已对接';
          badge.classList.add('live');
        }
      } else if (badge) {
        // 接口在线但暂无截图：维持动画 mockup
        badge.textContent = '演示';
      }
    } catch (e) {
      // 失败/超时同样保留动画 mockup（展示性优先），仅在 title 记录真实原因
      screen.setAttribute(
        'title',
        controller.signal.aborted ? '演示占位 · 加载超时，点 ↻ 重试' : '演示占位 · 加载失败：' + String(e)
      );
      if (badge) {
        badge.textContent = '演示';
        badge.classList.add('offline');
      }
    } finally {
      clearTimeout(timer);
      if (terminalFetchControllers[terminal] === controller) {
        delete terminalFetchControllers[terminal];
      }
      screen.classList.remove('aibiz-terminal-screen--loading');
    }
  }

  function formatTerminalBrief(terminal, data, pages) {
    const n = pages.length;
    const label = terminal === 'web' ? '网站' : terminal === 'software' ? '软件' : 'App';
    const android = data.android_audit || data.surface_audit?.android_audit;
    const cached = String(data.surface_audit_note || '').includes('缓存');
    let detail = '';
    if (terminal === 'web') detail = 'xiu-ci.com';
    else if (terminal === 'software') detail = '企业版';
    else if (android?.merged_count) detail = `adb ${android.merged_count}`;
    else detail = '企业版';
    return [label, n ? `${n} 页` : '待巡检', detail, cached ? '缓存' : '']
      .filter(Boolean)
      .join(' · ');
  }

  // ===== 截图轮播引擎（展示性 / 完整性 / 动画性）=====
  const terminalCarousels = {};

  function clearTerminalCarousel(terminal) {
    const c = terminalCarousels[terminal];
    if (c) {
      c.stopped = true;
      if (c.timer) clearTimeout(c.timer);
      c.timer = null;
    }
    terminalCarousels[terminal] = null;
  }

  function updateCarouselChrome(c, idx, page) {
    const root = c.root;
    if (!root) return;
    const nm = root.querySelector('.aibiz-shot-cap .nm');
    const ix = root.querySelector('.aibiz-shot-cap .ix');
    const st = root.querySelector('.aibiz-shot-cap .st');
    if (nm) nm.textContent = page.name || page.url || '页面';
    if (ix) ix.textContent = idx + 1 + ' / ' + c.list.length;
    if (st) {
      const bad = (page.status || 0) >= 400;
      st.textContent = 'HTTP ' + (page.status || '—');
      st.className = 'st ' + (bad ? 'bad' : 'ok');
    }
    const thumbs = root.querySelectorAll('.aibiz-shot-thumb');
    thumbs.forEach((t, i) => t.classList.toggle('is-active', i === idx));
    const active = thumbs[idx];
    const strip = root.querySelector('.aibiz-shot-thumbs');
    if (active && strip) {
      strip.scrollTo({
        left: active.offsetLeft - strip.clientWidth / 2 + active.clientWidth / 2,
        behavior: 'smooth',
      });
    }
    const prog = root.querySelector('.aibiz-shot-progress i');
    if (prog) {
      prog.style.animation = 'none';
      void prog.offsetWidth;
      if (!screenshotPrefersReducedMotion() && !c.paused && c.list.length > 1) {
        prog.style.animation = `aibizShotProg ${c.interval}ms linear`;
      }
    }
    c.screen.dataset.shotIndex = String(idx);
  }

  function setCarouselSlide(terminal, idx) {
    const c = terminalCarousels[terminal];
    if (!c || c.stopped || !c.list.length) return;
    idx = ((idx % c.list.length) + c.list.length) % c.list.length;
    c.index = idx;
    const page = c.list[idx];
    updateCarouselChrome(c, idx, page);
    preloadScreenshotImage(terminal, idx, page).then((loaded) => {
      const cc = terminalCarousels[terminal];
      if (!cc || cc !== c || c.stopped || c.index !== idx) return;
      const next = c.imgs[c.active ^ 1];
      const prev = c.imgs[c.active];
      next.src =
        loaded && loaded.ok && loaded.src
          ? loaded.src
          : surfaceImgSrc(terminal, idx, page, terminal === 'app' ? '' : 'viewport');
      next.alt = page.name || 'screenshot';
      next.classList.add('is-active');
      prev.classList.remove('is-active');
      c.active ^= 1;
      const nb = (idx + 1) % c.list.length;
      preloadScreenshotImage(terminal, nb, c.list[nb]);
    });
    if (c.timer) clearTimeout(c.timer);
    if (c.list.length > 1 && !screenshotPrefersReducedMotion()) {
      const tick = () => {
        const cc = terminalCarousels[terminal];
        if (!cc || cc.stopped) return;
        if (cc.paused) {
          cc.timer = setTimeout(tick, 700);
          return;
        }
        setCarouselSlide(terminal, cc.index + 1);
      };
      c.timer = setTimeout(tick, c.interval);
    }
  }

  function bindLazyShotThumbs(root, terminal, pages) {
    const strip = root.querySelector('.aibiz-shot-thumbs');
    const imgs = root.querySelectorAll('.aibiz-shot-thumb img[data-src]');
    const loadImg = (img) => {
      const src = img.getAttribute('data-src');
      if (!src || img.dataset.loaded) return;
      img.dataset.loaded = '1';
      img.src = src;
    };
    if (!('IntersectionObserver' in window) || !strip) {
      imgs.forEach(loadImg);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          loadImg(entry.target);
          io.unobserve(entry.target);
        });
      },
      { root: strip, rootMargin: '48px' }
    );
    imgs.forEach((img) => io.observe(img));
  }

  function renderTerminalScreen(screen, data, terminal) {
    const surface = data.surface_audit || {};
    const pages = Array.isArray(surface.pages) ? surface.pages : [];
    surfaceCacheByTerminal[terminal] = pages;
    const terminalLabel = terminal === 'web' ? '网站' : terminal === 'software' ? '软件' : 'App';

    clearTerminalCarousel(terminal);
    if (!pages.length) return; // 无截图：保留动画 mockup

    screen.classList.add('aibiz-terminal-screen--clickable', 'aibiz-terminal-screen--shots');
    screen.setAttribute('title', '点击查看全部 ' + pages.length + ' 页截图');
    screen.setAttribute('role', 'button');
    screen.setAttribute('tabindex', '0');

    const heroIndex =
      typeof surface.preview_index === 'number'
        ? surface.preview_index
        : pages.findIndex((p) => p && p.preview);
    const heroI = heroIndex >= 0 ? heroIndex : 0;
    const brief = formatTerminalBrief(terminal, data, pages);
    const thumbs = pages
      .map(
        (p, i) =>
          `<button type="button" class="aibiz-shot-thumb" data-aibiz-shot-thumb="${i}" title="${esc(p.name || '')}">` +
          `<img loading="lazy" decoding="async" alt="${esc(p.name || '')}" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" data-src="${esc(surfaceImgSrc(terminal, i, p, 'thumb'))}" />` +
          `</button>`
      )
      .join('');

    screen.innerHTML =
      `<div class="aibiz-terminal-label">${esc(terminalLabel)}</div>` +
      `<div class="aibiz-shot" data-aibiz-shot="${terminal}">` +
      `<div class="aibiz-shot-stage">` +
      `<img class="aibiz-shot-img" alt="" />` +
      `<img class="aibiz-shot-img" alt="" />` +
      `<div class="aibiz-shot-progress"><i></i></div>` +
      `<div class="aibiz-shot-grad"></div>` +
      `<span class="aibiz-shot-open" data-aibiz-shot-open>⤢ 全部 ${pages.length} 页</span>` +
      `<div class="aibiz-shot-cap"><span class="nm"></span><span class="meta"><span class="st ok"></span><span class="ix"></span></span></div>` +
      `</div>` +
      `<div class="aibiz-shot-thumbs">${thumbs}</div>` +
      `</div>` +
      `<div class="aibiz-terminal-analysis" title="${esc(brief)}">${esc(brief)}</div>`;

    const root = screen.querySelector('.aibiz-shot');
    const imgEls = root.querySelectorAll('.aibiz-shot-img');
    const c = {
      terminal,
      root,
      screen,
      list: pages,
      imgs: [imgEls[0], imgEls[1]],
      active: 0,
      index: heroI,
      interval: terminal === 'app' ? 2600 : 3000,
      paused: document.hidden,
      stopped: false,
      timer: null,
    };
    terminalCarousels[terminal] = c;

    bindLazyShotThumbs(root, terminal, pages);

    root.addEventListener('mouseenter', () => {
      c.paused = true;
      const p = root.querySelector('.aibiz-shot-progress i');
      if (p) p.style.animationPlayState = 'paused';
    });
    root.addEventListener('mouseleave', () => {
      c.paused = false;
      const p = root.querySelector('.aibiz-shot-progress i');
      if (p) p.style.animationPlayState = 'running';
    });
    root.querySelectorAll('[data-aibiz-shot-thumb]').forEach((btn) => {
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const i = parseInt(btn.getAttribute('data-aibiz-shot-thumb'), 10) || 0;
        openTerminalScreenshotGallery(terminal, surfaceCacheByTerminal[terminal], i);
      });
    });
    const openBtn = root.querySelector('[data-aibiz-shot-open]');
    if (openBtn) {
      openBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        openTerminalScreenshotGallery(terminal, surfaceCacheByTerminal[terminal], c.index);
      });
    }

    setCarouselSlide(terminal, heroI);
  }

  function refreshTerminalWeb(refresh) {
    return refreshTerminal(
      'web',
      `/api/xcmax/aibiz/web-terminal${terminalApiQuery(refresh, true)}`,
      '.aibiz-terminal--web .aibiz-terminal-screen',
      '.aibiz-terminal--web .aibiz-terminal-badge',
      refresh
    );
  }

  function refreshTerminalDesk(refresh) {
    return refreshTerminal(
      'software',
      `/api/xcmax/aibiz/desk-terminal${terminalApiQuery(refresh, true)}`,
      '.aibiz-terminal--desk .aibiz-terminal-screen',
      '.aibiz-terminal--desk .aibiz-terminal-badge',
      refresh
    );
  }

  function refreshTerminalApp(refresh) {
    return refreshTerminal(
      'app',
      `/api/xcmax/aibiz/app-terminal${terminalApiQuery(refresh, true)}`,
      '.aibiz-terminal--app .aibiz-terminal-screen',
      '.aibiz-terminal--app .aibiz-terminal-badge',
      refresh
    );
  }

  async function refreshCatalog() {
    const wrap = document.getElementById('aibiz-catalog-body');
    if (!wrap) return;
    wrap.innerHTML = '<div class="aibiz-catalog-loading">加载模型目录…</div>';
    try {
      const r = await fetch(api('/api/market/llm-catalog'), { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      const data = j.data || j;
      const providers = data.providers || data.items || [];
      if (!Array.isArray(providers) || !providers.length) throw new Error('empty');
      const rows = [];
      providers.forEach((p) => {
        const pid = p.id || p.provider_id || p.name || '—';
        const models = p.models || p.model_ids || [];
        if (Array.isArray(models) && models.length) {
          models.forEach((m) => {
            const mid = typeof m === 'string' ? m : m.id || m.model || '—';
            const price = typeof m === 'object' && m.price_per_1k != null ? m.price_per_1k : '—';
            rows.push(`<tr><td><code>${esc(pid)}</code></td><td>${esc(mid)}</td><td>${esc(price)}</td><td>MODstore 目录</td></tr>`);
          });
        } else {
          rows.push(`<tr><td><code>${esc(pid)}</code></td><td>—</td><td>—</td><td>MODstore 目录</td></tr>`);
        }
      });
      wrap.innerHTML =
        '<table class="emp-wf-cadence-table aibiz-table"><thead><tr><th>Provider</th><th>Model</th><th>单价/1K</th><th>来源</th></tr></thead><tbody>' +
        rows.join('') +
        '</tbody></table>';
    } catch (_) {
      wrap.innerHTML =
        '<div class="aibiz-catalog-fallback">' +
        '<p>未连上 FHD <code>/api/market/llm-catalog</code>（需登录或本地栈）。Token 计费真相源：</p>' +
        '<ul class="aibiz-ssot-list">' +
        '<li><code>FHD/app/infrastructure/llm/observability.py</code> · <code>record_llm_usage()</code> 结构化日志（prompt / completion / total tokens + 估算 USD）</li>' +
        '<li><code>FHD/app/fastapi_routes/domains/market_account/routes.py</code> · 钱包扣费与 <code>/api/market/account-overview</code></li>' +
        '<li>Prometheus：<code>ai_requests_total</code> · <code>ai_request_errors_total</code> · <code>chat_stream_first_byte_seconds</code></li>' +
        '</ul></div>';
    }
  }

  function catalogDetailsOpen() {
    const det = document.getElementById('aibiz-catalog-details');
    return !!(det && det.open);
  }

  function bindCatalogFold() {
    const det = document.getElementById('aibiz-catalog-details');
    if (!det || det.dataset.bound === '1') return;
    det.dataset.bound = '1';
    det.addEventListener('toggle', () => {
      if (det.open) refreshCatalog();
    });
  }

  async function refreshAll() {
    const jobs = [refreshKpis(), refreshByService()];
    if (catalogDetailsOpen()) jobs.push(refreshCatalog());
    await Promise.all(jobs);
    await Promise.all([
      refreshTerminalWeb(false),
      refreshTerminalDesk(false),
      refreshTerminalApp(false),
    ]);
  }

  function onAibizTab() {
    animateCounters(true);
    bindCatalogFold();
    refreshAll();
  }

  document.addEventListener('xcagi-tab-shown', (ev) => {
    if (ev.detail && ev.detail.tab === 'aibiz') onAibizTab();
  });

  const refreshBtn = document.getElementById('aibiz-refresh-btn');
  if (refreshBtn) refreshBtn.addEventListener('click', () => refreshAll());

  document.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-aibiz-pages-toggle]');
    if (!btn) return;
    ev.stopPropagation();
    const wrap = btn.closest('[data-aibiz-pages-wrap]');
    const list = wrap && wrap.querySelector('.aibiz-terminal-pages-list');
    if (!wrap || !list) return;
    const collapsed = wrap.classList.toggle('is-collapsed');
    const n = list.querySelectorAll('.aibiz-terminal-page-row').length;
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    btn.textContent = collapsed
      ? `共 ${n} 页 · 点击展开列表 · 点终端看全部截图`
      : `收起页面列表（${n} 页）· 点终端看全部截图`;
  });

  document.querySelectorAll('[data-aibiz-terminal-refresh]').forEach((btn) => {
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const term = btn.getAttribute('data-aibiz-terminal-refresh');
      if (term === 'web') refreshTerminalWeb(true);
      else if (term === 'software') refreshTerminalDesk(true);
      else if (term === 'app') refreshTerminalApp(true);
    });
  });

  function bindTerminalGallery(screenId, terminal) {
    const screen = document.getElementById(screenId);
    if (!screen) return;
    const openAtCurrent = () =>
      openTerminalScreenshotGallery(
        terminal,
        surfaceCacheByTerminal[terminal],
        parseInt(screen.dataset.shotIndex || '0', 10)
      );
    screen.addEventListener('click', openAtCurrent);
    screen.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        openAtCurrent();
      }
    });
  }

  document.addEventListener('visibilitychange', () => {
    const hidden = document.hidden;
    Object.keys(terminalCarousels).forEach((t) => {
      const c = terminalCarousels[t];
      if (c) c.paused = hidden;
    });
  });

  bindTerminalGallery('aibiz-terminal-web-screen', 'web');
  bindTerminalGallery('aibiz-terminal-desk-screen', 'software');
  bindTerminalGallery('aibiz-terminal-app-screen', 'app');

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      if (document.getElementById('s-aibiz')?.classList.contains('active')) onAibizTab();
    });
  } else if (document.getElementById('s-aibiz')?.classList.contains('active')) {
    onAibizTab();
  }

  window.MonAiBiz = {
    refreshAll,
    refreshTerminalWeb,
    refreshTerminalDesk,
    refreshTerminalApp,
    openWebScreenshotGallery,
    openTerminalScreenshotGallery,
  };
})();
