type RouteModuleLoader = () => Promise<Record<string, unknown>>

/** 企业版：预打包通用 bridge 与账号定制交付路由。 */
export const modRouteGlob = {
  ...import.meta.glob('../../../mods/taiyangniao-pro/frontend/routes.js'),
  ...import.meta.glob('../../../mods/sz-qsm-pro/frontend/routes.js'),
  ...import.meta.glob('../../../mods/coating-industry/frontend/routes.js'),
  ...import.meta.glob('../../../mods/xcagi-planner-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/xcagi-erp-domain-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/xcagi-workflow-visualization-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/xcagi-approval-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/xcagi-lan-license-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/xcagi-model-payment-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/xcagi-neuro-bus-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/xcagi-office-employee-pack-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/xcagi-customer-service-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/xcagi-core-workflow-employees/frontend/routes.js'),
  ...import.meta.glob('../../../mods/lan-gate-ai-employee/frontend/routes.js'),
  ...import.meta.glob('../../../mods/wechat-contacts-ai-employee/frontend/routes.js'),
} as Record<string, RouteModuleLoader>
