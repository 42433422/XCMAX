import type { RouteLocationRaw } from 'vue-router'
import { CORE_WORKFLOW_MOD_ID, readCoreWorkflowModPagesEnabled } from '@/constants/coreWorkflowMod'

const WORKFLOW_VIZ_MOD_PATH = `/mod/${CORE_WORKFLOW_MOD_ID}/workflow-visualization`

/** 流程可视化页路由（Mod 门面开启时走物理视图路径） */
export function resolveWorkflowVisualizationLocation(): RouteLocationRaw {
  if (readCoreWorkflowModPagesEnabled()) {
    return { path: WORKFLOW_VIZ_MOD_PATH }
  }
  return { name: 'workflow-visualization' }
}

export function workflowVisualizationModPath(): string {
  return WORKFLOW_VIZ_MOD_PATH
}
