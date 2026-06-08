/**
 * 全景仪表盘 API 基址 — file:// 或 Live Server 等无 /api 反代时回退到 :8765
 * 经 FHD / Vite 挂载 /xcmax-dashboard 时走页面同源（:5001 → :5100 代理），勿直连 :8765
 * 用法：XCAGIApi.url('/api/xcmax/aibiz/web-terminal')
 */
(function (global) {
  'use strict';

  const LEGACY_DEV_ORIGIN = 'http://127.0.0.1:8765';
  const LEGACY_DEV_PORT = '8765';
  const DEFAULT_FHD_API_ORIGIN = 'http://127.0.0.1:5100';
  /** FHD / Vite 企业开发常用端口（AirPlay 占用 :5000 时后端可能在 :5100） */
  const FHD_EMBED_PORTS = new Set(['5000', '5001', '5100', '5101', '8000']);
  const PROXY_PREFIXES = ['/api', '/metrics', '/prometheus', '/grafana'];

  function loc() {
    return global.location || {};
  }

  function isLocalHost(hostname) {
    const h = String(hostname || '').toLowerCase();
    return h === 'localhost' || h === '127.0.0.1' || h === '[::1]';
  }

  function pageOrigin() {
    const o = loc().origin;
    if (o && o !== 'null') return o.replace(/\/$/, '');
    return '';
  }

  /** 经 AutomationPolicy iframe 等嵌入 FHD 前端（勿把 legacy :8765 独立服误判为嵌入） */
  function isFhdDashboardEmbed() {
    const l = loc();
    const path = String(l.pathname || '');
    if (path.includes('/xcmax-dashboard')) return true;
    const port = String(l.port || (l.protocol === 'https:' ? '443' : '80'));
    if (port === LEGACY_DEV_PORT) return false;
    return (
      isLocalHost(l.hostname) &&
      FHD_EMBED_PORTS.has(port) &&
      (path.includes('XCAGI-Full-Pipeline') || path.includes('XCAGI-Five-Line'))
    );
  }

  function isStaticJsonPath(rel) {
    const bare = String(rel || '').split('?')[0].split('#')[0];
    return (
      bare.startsWith('FHD/') ||
      bare.startsWith('docs/xcagi-dashboard/') ||
      bare.startsWith('.cache/') ||
      bare.endsWith('.json') ||
      bare.startsWith('six_line_') ||
      bare.startsWith('xcmax-')
    );
  }

  function needsProxyOrigin() {
    const l = loc();
    if (l.protocol === 'file:') return true;
    if (isFhdDashboardEmbed()) return true;
    if (!isLocalHost(l.hostname)) return false;
    const port = String(l.port || (l.protocol === 'https:' ? '443' : '80'));
    return port !== LEGACY_DEV_PORT;
  }

  /** FHD FastAPI — /api/xcmax/* 仅存在于 FHD，不在轻量 MODstore :8765 */
  function fhdApiOrigin() {
    const forced = global.XCAGI_FHD_API_ORIGIN || global.XCAGI_API_BACKEND;
    if (forced) return String(forced).replace(/\/$/, '');
    if (isFhdDashboardEmbed()) {
      const o = pageOrigin();
      if (o) return o;
    }
    return DEFAULT_FHD_API_ORIGIN;
  }

  function isXcmaxApiPath(rel) {
    return rel === '/api/xcmax' || rel.startsWith('/api/xcmax/');
  }

  function forcedOrigin() {
    const forced =
      global.XCAGI_DASHBOARD_ORIGIN || global.XCAGI_OPS_HEALTH_URL || global.XCAGI_MODSTORE_URL;
    if (forced) return String(forced).replace(/\/$/, '');
    return '';
  }

  function dashboardOrigin() {
    const forced = forcedOrigin();
    if (forced) return forced;
    if (isFhdDashboardEmbed()) {
      const o = pageOrigin();
      if (o) return o;
    }
    if (!needsProxyOrigin()) return pageOrigin() || LEGACY_DEV_ORIGIN;
    return LEGACY_DEV_ORIGIN;
  }

  /** /api /metrics /prometheus /grafana 反代目标 */
  function proxyTargetOrigin() {
    const forced = forcedOrigin();
    if (forced) return forced;
    if (isFhdDashboardEmbed()) {
      const o = pageOrigin();
      if (o) return o;
    }
    return LEGACY_DEV_ORIGIN;
  }

  function url(path) {
    const p = String(path || '');
    if (/^https?:\/\//i.test(p)) return p;
    const rel = p.startsWith('/') ? p : '/' + p;
    if (isXcmaxApiPath(rel)) {
      return fhdApiOrigin() + rel;
    }
    const useProxy =
      needsProxyOrigin() && PROXY_PREFIXES.some((pre) => rel === pre || rel.startsWith(pre + '/'));
    const origin = useProxy ? proxyTargetOrigin() : dashboardOrigin();
    return origin + rel;
  }

  /** 嵌入 FHD 时静态 JSON 应走 /xcmax-dashboard/ 前缀，避免 /FHD/… 落到 Vue index.html */
  function staticUrl(relPath) {
    const raw = String(relPath || '');
    if (!raw || /^https?:\/\//i.test(raw)) return relPath;
    if (raw.startsWith('/xcmax-dashboard/')) return raw;
    const rel = raw.replace(/^\//, '');
    if (!rel) return relPath;
    if (isFhdDashboardEmbed() && isStaticJsonPath(rel)) {
      return '/xcmax-dashboard/' + rel;
    }
    return raw.startsWith('/') ? raw : rel;
  }

  async function fetchJson(resource, init) {
    const target =
      typeof resource === 'string' && !/^https?:\/\//i.test(resource)
        ? staticUrl(resource)
        : resource;
    try {
      const r = await fetch(target, init);
      if (!r.ok) return null;
      const ct = (r.headers.get('content-type') || '').toLowerCase();
      if (ct.includes('text/html')) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

  global.XCAGIApi = {
    defaultOrigin: LEGACY_DEV_ORIGIN,
    fhdApiOrigin: fhdApiOrigin(),
    origin: dashboardOrigin(),
    url,
    staticUrl,
    fetchJson,
    isFileProtocol: !!(loc().protocol === 'file:'),
    isFhdEmbed: isFhdDashboardEmbed(),
    needsDevServer: needsProxyOrigin,
    devServerHint: isFhdDashboardEmbed()
      ? '已嵌入 FHD：API 走当前页同源（请确认 Vite/FHD 已启动且 /api 可代理）'
      : '请用 bash scripts/serve_xcagi_dashboard.sh 打开 http://127.0.0.1:8765/XCAGI-Full-Pipeline.html，并在 :5000/:5100 启动 FHD',
  };
})(typeof window !== 'undefined' ? window : globalThis);
