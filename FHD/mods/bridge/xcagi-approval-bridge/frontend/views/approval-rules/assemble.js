import { onMounted } from 'vue'
import { useApprovalRulesConfig } from './useApprovalRulesConfig'
import { useRuleEditor } from './useRuleEditor'
import { getActionLabel, getTriggerLabel, formatTime } from './ruleLabels'

/**
 * 组装审批规则视图全部状态与动作；子组件通过单一 ctx prop 共享，
 * 逻辑自 ApprovalRulesView.vue 逐字迁移，行为不变。
 */
export function assembleApprovalRules() {
  const config = useApprovalRulesConfig()
  const editor = useRuleEditor({ rules: config.rules, saveConfig: config.saveConfig })

  onMounted(() => {
    config.loadConfig()
  })

  return {
    ...config,
    ...editor,
    // 纯工具函数随 ctx 暴露给模板（原 SFC 脚本内直接可见）
    getActionLabel,
    getTriggerLabel,
    formatTime,
  }
}

export default assembleApprovalRules
