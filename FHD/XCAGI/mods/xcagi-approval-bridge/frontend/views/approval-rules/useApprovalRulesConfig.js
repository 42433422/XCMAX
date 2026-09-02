import { ref } from 'vue'
import { appAlert } from '@/utils/appDialog'

/**
 * 拆分自 ApprovalRulesView.vue 脚本（原第 139–141、185–228、271–314 行）；
 * 逻辑逐字迁移，行为不变。
 */
export function useApprovalRulesConfig() {
  const enabled = ref(true)
  const rules = ref([])
  const pendingApprovals = ref([])

  const toggleEnabled = async () => {
    enabled.value = !enabled.value
    await saveConfig()
  }

  const loadConfig = async () => {
    try {
      const response = await fetch('/api/ai/approval/pending')
      const data = await response.json()
      if (data.success) {
        pendingApprovals.value = data.data?.pending_approvals || []
      }
    } catch (e) {
      console.error('加载待审批列表失败', e)
    }

    try {
      const response = await fetch('/api/ai/config/approval')
      const data = await response.json()
      if (data.enabled !== undefined) {
        enabled.value = data.enabled
      }
      if (data.rules) {
        rules.value = data.rules
      }
    } catch (e) {
      console.error('加载审批配置失败', e)
    }
  }

  const saveConfig = async () => {
    try {
      await fetch('/api/ai/config/approval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: enabled.value,
          rules: rules.value
        })
      })
    } catch (e) {
      console.error('保存审批配置失败', e)
    }
  }

  const approveItem = async (item) => {
    try {
      const response = await fetch('/api/ai/approval/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_id: item.plan_id })
      })
      const data = await response.json()
      if (data.success) {
        await appAlert(data.message || '审批已通过')
        if (data.data?.workflow_executed && data.data?.workflow_result) {
          const wr = data.data.workflow_result
          console.log('工作流执行结果:', wr)
          await appAlert(
            `工作流已执行完成！\n` +
            `执行节点: ${wr.nodes_executed}/${wr.nodes_total}\n` +
            `状态: ${wr.has_errors ? '有错误' : '成功'}`
          )
        }
        await loadConfig()
      } else {
        await appAlert(data.message || '审批失败')
      }
    } catch (e) {
      console.error('审批失败', e)
      await appAlert('审批请求失败: ' + e.message)
    }
  }

  const rejectItem = async (item) => {
    try {
      const response = await fetch('/api/ai/approval/reject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_id: item.plan_id })
      })
      const data = await response.json()
      if (data.success) {
        await loadConfig()
      }
    } catch (e) {
      console.error('拒绝失败', e)
    }
  }

  return { enabled, rules, pendingApprovals, toggleEnabled, loadConfig, saveConfig, approveItem, rejectItem }
}
