type RouteModuleLoader = () => Promise<Record<string, unknown>>

/** 通用宿主预注册内置 ERP 与审批路由；其余可选行业 Mod 仍按交付策略加载。 */
export const modRouteGlob = {
  ...import.meta.glob('../../../mods/xcagi-erp-domain-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/xcagi-approval-bridge/frontend/routes.js'),
} as Record<string, RouteModuleLoader>
