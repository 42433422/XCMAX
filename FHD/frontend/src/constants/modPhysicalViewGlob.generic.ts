type ViewLoader = () => Promise<{ default: unknown }>

/**
 * 通用宿主内置企业业务底座：ERP 领域页 + 审批工作台。
 *
 * 行业 Mod 可以替换字段、流程和侧栏骨架，但业务对象、组织、单据、
 * 记录、物料、库存与人机审批闭环不能依赖运行后再安装。Vite 的 glob 是
 * 构建期注册表，漏项会让已随宿主交付的内置 Mod 被误判为商店扩展。
 */
export const modPhysicalViewGlob = {
  ...import.meta.glob('../../../mods/xcagi-erp-domain-bridge/frontend/views/**/*.vue'),
  ...import.meta.glob('../../../mods/xcagi-approval-bridge/frontend/views/**/*.vue'),
} as Record<string, ViewLoader>
