import { ref, computed } from 'vue'
import { approvalApi, type ApprovalFlow, type ApprovalFlowNode } from '@/api/approval'
import { appAlert } from '@/utils/appDialog'

/**
 * 拆分自 ApprovalFlowManagementView.vue 脚本（原第 211–239、253–362 行）；
 * 逻辑逐字迁移，行为不变。saveFlow 保存后需刷新列表，loadFlows 经 deps 注入。
 */
export function useFlowForm(deps: { loadFlows: () => Promise<void> }) {
  const showCreateModal = ref(false)
  const editingFlow = ref<ApprovalFlow | null>(null)

  // 表单数据
  const formData = ref({
    flow_name: '',
    flow_key: '',
    business_type: '',
    description: '',
    is_active: true,
    nodes: [] as Array<{
      node_name: string
      node_type: string
      node_order: number
      approver_type: string
      approver_ids: number[]
      approver_ids_text: string
      is_active: boolean
    }>
  })

  const canSave = computed(() => {
    return (
      formData.value.flow_name &&
      formData.value.flow_key &&
      formData.value.business_type &&
      formData.value.nodes.length > 0
    )
  })

  // 创建流程
  const addNode = () => {
    formData.value.nodes.push({
      node_name: '',
      node_type: 'serial',
      node_order: formData.value.nodes.length + 1,
      approver_type: 'user',
      approver_ids: [],
      approver_ids_text: '',
      is_active: true
    })
  }

  const removeNode = (index: number) => {
    formData.value.nodes.splice(index, 1)
    // 重新排序
    formData.value.nodes.forEach((node, idx) => {
      node.node_order = idx + 1
    })
  }

  const resetForm = () => {
    formData.value = {
      flow_name: '',
      flow_key: '',
      business_type: '',
      description: '',
      is_active: true,
      nodes: []
    }
    editingFlow.value = null
  }

  const closeModal = () => {
    showCreateModal.value = false
    resetForm()
  }

  const editFlow = (flow: ApprovalFlow) => {
    editingFlow.value = flow
    formData.value = {
      flow_name: flow.flow_name,
      flow_key: flow.flow_key,
      business_type: flow.business_type,
      description: flow.description || '',
      is_active: flow.is_active,
      nodes: (flow.nodes || []).map((node: ApprovalFlowNode) => ({
        ...node,
        approver_ids_text: Array.isArray(node.approver_ids)
          ? node.approver_ids.join(',')
          : node.approver_ids || ''
      }))
    }
    showCreateModal.value = true
  }

  const saveFlow = async () => {
    if (!canSave.value) {
      await appAlert('请填写必填项')
      return
    }

    // 转换审批人 ID
    const nodes = formData.value.nodes.map(node => ({
      node_name: node.node_name,
      node_type: node.node_type,
      node_order: node.node_order,
      approver_type: node.approver_type,
      approver_ids: node.approver_ids_text
        ? node.approver_ids_text.split(',').map(id => parseInt(id.trim())).filter(id => !isNaN(id))
        : [],
      is_active: node.is_active
    }))

    try {
      const flowData = {
        flow_name: formData.value.flow_name,
        flow_key: formData.value.flow_key,
        business_type: formData.value.business_type,
        description: formData.value.description,
        is_active: formData.value.is_active
      }

      let res
      if (editingFlow.value) {
        res = await approvalApi.updateFlow(editingFlow.value.id, { ...flowData })
        if (res?.success) {
          await appAlert('流程更新成功！')
          closeModal()
          deps.loadFlows()
        } else {
          await appAlert('更新失败：' + (res?.message || '未知错误'))
        }
        return
      } else {
        res = await approvalApi.createFlow(flowData, nodes)
      }

      if (res.success) {
        await appAlert('流程创建成功！')
        closeModal()
        deps.loadFlows()
      } else {
        await appAlert('创建失败：' + res.message)
      }
    } catch (error) {
      console.error('创建/更新流程失败:', error)
      await appAlert('操作失败，请重试')
    }
  }

  return {
    showCreateModal, editingFlow, formData, canSave,
    addNode, removeNode, closeModal, editFlow, saveFlow,
  }
}
