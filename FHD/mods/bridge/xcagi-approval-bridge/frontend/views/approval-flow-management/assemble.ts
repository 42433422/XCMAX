import { onMounted } from 'vue'
import { useFlowList } from './useFlowList'
import { useFlowForm } from './useFlowForm'

/**
 * 组装审批流程管理视图全部状态与动作；子组件通过单一 ctx prop 共享，
 * 逻辑自 ApprovalFlowManagementView.vue 逐字迁移，行为不变。
 */
export function assembleApprovalFlowManagement() {
  const list = useFlowList()
  const form = useFlowForm({ loadFlows: list.loadFlows })

  onMounted(() => {
    list.loadFlows()
  })

  return {
    ...list,
    ...form,
  }
}

export type ApprovalFlowManagementCtx = ReturnType<typeof assembleApprovalFlowManagement>
