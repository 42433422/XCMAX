type RouteModuleLoader = () => Promise<Record<string, unknown>>

/** 企业版：预打包通用 bridge 与账号定制交付路由。 */
export const modRouteGlob = {
  ...import.meta.glob('../../../mods/industry/taiyangniao-pro/frontend/routes.js'),
  ...import.meta.glob('../../../mods/industry/sz-qsm-pro/frontend/routes.js'),
  ...import.meta.glob('../../../mods/industry/coating-industry/frontend/routes.js'),
  // attendance-industry 是当前仅存在于 XCAGI/mods 的兼容交付模块。
  ...import.meta.glob('../../../XCAGI/mods/attendance-industry/frontend/routes.js'),
  ...import.meta.glob('../../../mods/bridge/xcagi-planner-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/bridge/xcagi-erp-domain-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/bridge/xcagi-workflow-visualization-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/bridge/xcagi-approval-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/bridge/xcagi-lan-license-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/bridge/xcagi-model-payment-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/bridge/xcagi-neuro-bus-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/bridge/xcagi-office-employee-pack-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/bridge/xcagi-customer-service-bridge/frontend/routes.js'),
  ...import.meta.glob('../../../mods/employees/xcagi-core-workflow-employees/frontend/routes.js'),
  ...import.meta.glob('../../../mods/employees/lan-gate-ai-employee/frontend/routes.js'),
} as Record<string, RouteModuleLoader>
