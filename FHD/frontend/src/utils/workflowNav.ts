import type { RouteLocationRaw } from 'vue-router'
import { CORE_WORKFLOW_MOD_ID, readCoreWorkflowModPagesEnabled } from '@/constants/coreWorkflowMod'

const WORKFLOW_VIZ_MOD_PATH = `/mod/${CORE_WORKFLOW_MOD_ID}/workflow-visualization`

/** 流程可视化页路由（Mod 门面开启时走物理视图路径） */
export function resolveWorkflowVisualizationLocation(): RouteLocationRaw {
  if (readCoreWorkflowModPagesEnabled()) {
    return { path: WORKFLOW_VIZ_MOD_PATH }
  }
  // 宿主 workflow-visualization 路由仅在管理端构建注册；企业/通用构建用普通路径，
  // 避免 router-link 解析不存在的具名路由抛错导致整页渲染失败。
  if (import.meta.env.VITE_XCMAX_ADMIN_CONSOLE === '1') {
    return { name: 'workflow-visualization' }
  }
  return { path: WORKFLOW_VIZ_MOD_PATH }
}

export function workflowVisualizationModPath(): string {
  return WORKFLOW_VIZ_MOD_PATH
}
