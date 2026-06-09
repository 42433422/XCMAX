/**
 * XCAGI Dashboard 单点 SOT（Single Source of Truth）
 *
 * 全部 dashboard JS / JSON / HTML 的 ?v= 缓存击穿参数都应从本文件派生，
 * 避免散落在 30+ 处的 `?v=202606xx` 各版本号漂移。
 *
 * 升级步骤（人工 bump）：
 *   1. 修改 SOT_VERSION；
 *   2. 跑 node scripts/bump-dashboard-sot.js（如果存在）或手工跑：
 *        `rg "\?v=20260" -l` 列出全部依赖文件，按 SOT 替换。
 *   3. 提交 + 部署 + 让浏览器重新拉资源（HTML cache-buster 也跟着升）。
 *
 * 对接方用法：
 *   <script src="docs/xcagi-dashboard/xcagi-dashboard-sot.js"></script>
 *   <script>
 *     const v = window.XCAGI_DASHBOARD_SOT.version;          // "2026-06-08"
 *     const url = window.XCAGI_DASHBOARD_SOT.bust('docs/xcagi-dashboard/app.js');
 *     // => "docs/xcagi-dashboard/app.js?v=20260608"
 *   </script>
 */
(function (root) {
  const SOT_VERSION = '2026-06-08';
  const SOT_DATE = SOT_VERSION.replace(/-/g, ''); // "20260608"
  const MODULE_BUMPS = {
    /* 个别模块如有额外版本后缀（k/n/u 等），可在此显式覆盖 */
    'docs/xcagi-dashboard/app.js': SOT_DATE + 'k',
    'docs/xcagi-dashboard/emp-wf-action-items.js': SOT_DATE + 'k',
  };
  /**
   * 给资源 URL 加 ?v= 缓存击穿；自动识别 .json / .js / .css。
   * 同一 URL 多次调用返回同一版本号（确保缓存命中稳定）。
   */
  function bust(url) {
    if (!url) return url;
    /* 已有 ?v= 的清掉再贴 */
    const base = String(url).split('?')[0];
    const suffix = MODULE_BUMPS[base] || SOT_DATE;
    return base + '?v=' + suffix;
  }
  /**
   * 移除 URL 中的 ?v= 参数（用于需要 cache-bust 关闭的场景）
   */
  function unbust(url) {
    if (!url) return url;
    return String(url).split('?')[0];
  }
  const api = {
    version: SOT_VERSION,
    date: SOT_DATE,
    bust,
    unbust,
  };
  root.XCAGI_DASHBOARD_SOT = api;
  /* 兼容旧名：XCAGIApi.sot、__XCAGI_SOT__ */
  root.__XCAGI_SOT__ = SOT_VERSION;
  if (root.XCAGIApi && typeof root.XCAGIApi === 'object') {
    root.XCAGIApi.sot = api;
  }
})(typeof window !== 'undefined' ? window : globalThis);
