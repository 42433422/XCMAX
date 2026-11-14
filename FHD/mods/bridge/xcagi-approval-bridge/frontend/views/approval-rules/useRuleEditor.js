import { ref, computed } from 'vue'

/**
 * 拆分自 ApprovalRulesView.vue 脚本（原第 142–154、230–269 行）；
 * 逻辑逐字迁移，行为不变。规则增删改依赖 rules 列表与 saveConfig，经 deps 注入。
 */
export function useRuleEditor(deps) {
  const { rules, saveConfig } = deps

  const editingIndex = ref(null)
  const editForm = ref({ description: '', trigger: 'always' })

  const newRule = ref({
    tool_id: '',
    action: '',
    trigger: 'always',
    description: ''
  })

  const canAddRule = computed(() => {
    return newRule.value.tool_id && newRule.value.action
  })

  const addRule = async () => {
    if (!canAddRule.value) return

    rules.value.push({
      tool_id: newRule.value.tool_id,
      action: newRule.value.action,
      trigger: newRule.value.trigger,
      description: newRule.value.description,
      conditions: {}
    })

    newRule.value = { tool_id: '', action: '', trigger: 'always', description: '' }
    await saveConfig()
  }

  const editRule = (index) => {
    editingIndex.value = index
    editForm.value = {
      description: rules.value[index].description || '',
      trigger: rules.value[index].trigger || 'always'
    }
  }

  const saveEdit = async () => {
    if (editingIndex.value !== null) {
      rules.value[editingIndex.value].description = editForm.value.description
      rules.value[editingIndex.value].trigger = editForm.value.trigger
      await saveConfig()
      closeEdit()
    }
  }

  const closeEdit = () => {
    editingIndex.value = null
  }

  const deleteRule = async (index) => {
    rules.value.splice(index, 1)
    await saveConfig()
  }

  return {
    editingIndex, editForm, newRule, canAddRule,
    addRule, editRule, saveEdit, closeEdit, deleteRule,
  }
}
