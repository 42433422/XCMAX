/**
 * Compute the keep-alive cache key for the App-level `<router-view>`.
 *
 * 顶层 keep-alive cache key 必须按"顶层壳组件"分桶，绝不能让两种不同的顶层
 * component 落到同一个 key 上，否则 keep-alive 会用旧实例去渲染新 vnode
 * （type 已变），随后 patch 在 unmount 旧 vnode 时拿到的 parentComponent 不是
 * KeepAlive 实例，就会抛
 *   TypeError: parentComponent.ctx.deactivate is not a function
 * （minified 后是 `d.ctx.deactivate is not a function`，发生在 vue-vendor 的
 * KeepAlive sharedContext.activate → patch → unmount 路径上，
 * 详见 @vue/runtime-core renderer 中 `if (shapeFlag & 256) { parentComponent.ctx.deactivate(...) }`）。
 *
 * 顶层壳分桶（与 router/index.ts 的 component 一一对应）：
 *  - WorkbenchShell    → name === 'workbench-shell'（实际路径 /workbench/shell/...）
 *  - WorkbenchView     → /workbench、/workbench/home、/workbench/unified、/workbench/mod/* 等
 *                       也包括根路径 /（重定向到 /workbench/home 后由 WorkbenchView 承载）
 *  - 其他页面以 fullPath 作 key
 *
 * 历史坑：之前用 `startsWith('/workbench-shell')`（带连字符）想分出 WorkbenchShell，
 * 但实际路径是 `/workbench/shell`（带斜杠），永远命中不到，结果 /workbench/shell/* 与
 * /workbench/home 共用同一 key 'cache-workbench-view' → keep-alive 取错 vnode → 上述异常。
 */
export interface TopLevelRouteSnapshot {
  path: string | null | undefined
  name: string | symbol | null | undefined
  fullPath: string | null | undefined
}

export function resolveTopLevelRouterCacheKey(route: TopLevelRouteSnapshot): string {
  const p = route.path || ''
  const n = typeof route.name === 'string' ? route.name : route.name ? String(route.name) : ''

  if (n === 'workbench-shell') return 'cache-workbench-shell-v2'
  if (p === '/workbench' || p.startsWith('/workbench/') || p === '/') return 'cache-workbench-view'
  return route.fullPath || p || '/'
}
