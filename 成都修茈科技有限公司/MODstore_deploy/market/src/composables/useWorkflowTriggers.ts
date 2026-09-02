import { ref, type Ref } from 'vue'
import { api } from '../api'
import { errMessage } from '../utils/errMessage'
import type { TriggerRow, WorkflowRow } from '../views/workflow/workflowTypes'

/** WorkflowView 触发器域（自 WorkflowView.vue 原样迁移） */
export function useWorkflowTriggers(deps: {
  workflows: Ref<WorkflowRow[]>
  loadWorkflows: () => Promise<void>
}) {
  const { workflows, loadWorkflows } = deps

  const triggersWorkflowId = ref(0)
  const triggerRows = ref<TriggerRow[]>([])
  const triggersLoading = ref(false)
  const triggersMsg = ref('')
  const triggersMsgOk = ref(true)
  const triggersCronExpr = ref('0 9 * * *')
  const triggersWebhookJson = ref('{\n  "source": "webhook"\n}')

  async function loadTriggersPanel() {
    triggersLoading.value = true
    triggersMsg.value = ''
    try {
      if (!workflows.value.length) await loadWorkflows()
      if (!triggersWorkflowId.value && workflows.value.length) {
        triggersWorkflowId.value = workflows.value[0].id
      }
      await refreshTriggersList()
    } catch (e) {
      triggersMsgOk.value = false
      triggersMsg.value = errMessage(e)
    } finally {
      triggersLoading.value = false
    }
  }

  async function refreshTriggersList() {
    const wid = Number(triggersWorkflowId.value)
    if (!wid) {
      triggerRows.value = []
      return
    }
    const rows = await api.listWorkflowTriggers(wid)
    triggerRows.value = Array.isArray(rows) ? rows : []
  }

  function onTriggersWorkflowChange() {
    refreshTriggersList().catch((e) => {
      triggersMsgOk.value = false
      triggersMsg.value = errMessage(e)
    })
  }

  async function addCronTrigger() {
    const wid = Number(triggersWorkflowId.value)
    if (!wid) return
    triggersMsg.value = ''
    try {
      await api.createWorkflowTrigger(wid, {
        trigger_type: 'cron',
        trigger_key: '',
        config: { cron: triggersCronExpr.value.trim() || '0 0 * * *' },
        is_active: true,
      })
      triggersMsgOk.value = true
      triggersMsg.value = '已添加 Cron 触发器'
      await refreshTriggersList()
    } catch (e) {
      triggersMsgOk.value = false
      triggersMsg.value = errMessage(e)
    }
  }

  async function addWebhookTrigger() {
    const wid = Number(triggersWorkflowId.value)
    if (!wid) return
    triggersMsg.value = ''
    try {
      await api.createWorkflowTrigger(wid, {
        trigger_type: 'webhook',
        trigger_key: 'default',
        config: {},
        is_active: true,
      })
      triggersMsgOk.value = true
      triggersMsg.value = '已添加 Webhook 触发器'
      await refreshTriggersList()
    } catch (e) {
      triggersMsgOk.value = false
      triggersMsg.value = errMessage(e)
    }
  }

  async function removeTriggerRow(triggerId: number) {
    const wid = Number(triggersWorkflowId.value)
    if (!wid || !triggerId) return
    try {
      await api.deleteWorkflowTrigger(wid, triggerId)
      triggersMsgOk.value = true
      triggersMsg.value = '已停用触发器'
      await refreshTriggersList()
    } catch (e) {
      triggersMsgOk.value = false
      triggersMsg.value = errMessage(e)
    }
  }

  async function testWebhookTrigger() {
    const wid = Number(triggersWorkflowId.value)
    if (!wid) return
    triggersMsg.value = ''
    try {
      let payload = {}
      try {
        payload = JSON.parse(triggersWebhookJson.value || '{}')
      } catch {
        throw new Error('Webhook 测试 JSON 无效')
      }
      const res = await api.workflowWebhookRun(wid, payload)
      triggersMsgOk.value = true
      triggersMsg.value = `Webhook 测试成功：${JSON.stringify(res).slice(0, 500)}`
    } catch (e) {
      triggersMsgOk.value = false
      triggersMsg.value = errMessage(e)
    }
  }

  /** 仅重置本域内存态（原 resetAutomationWorkbenchLocalState 中的触发器部分） */
  function reset() {
    triggersMsg.value = ''
    triggersCronExpr.value = '0 9 * * *'
    triggersWebhookJson.value = '{\n  "source": "webhook"\n}'
    triggersWorkflowId.value = 0
    triggerRows.value = []
  }

  return {
    triggersWorkflowId,
    triggerRows,
    triggersLoading,
    triggersMsg,
    triggersMsgOk,
    triggersCronExpr,
    triggersWebhookJson,
    loadTriggersPanel,
    refreshTriggersList,
    onTriggersWorkflowChange,
    addCronTrigger,
    addWebhookTrigger,
    removeTriggerRow,
    testWebhookTrigger,
    reset,
  }
}
