type RouteModuleLoader = () => Promise<Record<string, unknown>>

/** full 构建 / 管理端 adminConsole.vite.config.js 专用；企业 :5001 用 generic 空 glob */
export const modRouteGlob = {
  ...import.meta.glob('../../../mods/*/frontend/routes.js'),
  ...import.meta.glob('../../../mods-admin-runtime/*/frontend/routes.js'),
} as Record<string, RouteModuleLoader>
