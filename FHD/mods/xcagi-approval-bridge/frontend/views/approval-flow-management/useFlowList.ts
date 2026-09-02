import { ref } from 'vue'
import { approvalApi, type ApprovalFlow } from '@/api/approval'
import { appAlert, appConfirm } from '@/utils/appDialog'

/**
 * 拆分自 ApprovalFlowManagementView.vue 脚本（原第 209–210、241–251、364–393 行）；
 * 逻辑逐字迁移，行为不变。
 */
export function useFlowList() {
  // 流程列表
  const flowList = ref<ApprovalFlow[]>([])

  // 加载流程列表
  const loadFlows = async () => {
    try {
      const res = await approvalApi.getFlowList()
      if (res.success && 'data' in res && res.data) {
        flowList.value = res.data.flows || []
      }
    } catch (error) {
      console.error('加载流程列表失败:', error)
    }
  }

  const toggleFlowStatus = async (flow: any) => {
    const newActive = !flow.is_active
    const res = await approvalApi.toggleFlowActive(flow.id, newActive)
    if (res?.success) {
      loadFlows()
    } else {
      await appAlert('切换状态失败：' + (res?.message || '未知错误'))
    }
  }

  const deleteFlow = async (flowId: number) => {
    if (!(await appConfirm('确定要删除此审批流程吗？', { danger: true }))) return
    const res = await approvalApi.deleteFlow(flowId)
    if (res?.success) {
      loadFlows()
    } else {
      await appAlert('删除失败：' + (res?.message || '未知错误'))
    }
  }

  const getBusinessTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      shipment: '出货单',
      purchase: '采购',
      expense: '费用报销',
      contract: '合同',
      general: '通用'
    }
    return labels[type] || type
  }

  return { flowList, loadFlows, toggleFlowStatus, deleteFlow, getBusinessTypeLabel }
}
