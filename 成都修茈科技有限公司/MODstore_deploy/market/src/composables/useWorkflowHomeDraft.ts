import { ref, watch, type Ref } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'

/** WorkflowView 首页带入草稿域（自 WorkflowView.vue 原样迁移） */
export function useWorkflowHomeDraft(deps: {
  route: RouteLocationNormalizedLoaded
  flash: (msg: string, ok?: boolean) => void
  newWorkflow: Ref<{ name: string; description: string }>
  showCreateModal: Ref<boolean>
}) {
  const { route, flash, newWorkflow, showCreateModal } = deps

  /** 从工作台首页带入的默认模型说明 */
  const homeLlmHint = ref('')
  /** 从工作台首页带入的制作类型（mod / employee / workflow） */
  const homeIntentHint = ref('')

  const INTENT_FROM_HOME: Record<string, string> = {
    mod: '从首页带入：做 Mod（仓库 + 行业 JSON + 员工命名）',
    employee: '从首页带入：做员工',
    workflow: '从首页带入：生成 Skill 组',
  }

  /** 原 onMounted 中读取 sessionStorage 首页草稿的段落，原样迁移 */
  function restoreHomeDraft() {
    try {
      const fromHome = sessionStorage.getItem('workbench_home_draft')
      const fromIntent = sessionStorage.getItem('workbench_home_intent')
      const fromLlm = sessionStorage.getItem('workbench_home_llm')
      const fromLlmMode = sessionStorage.getItem('workbench_home_llm_mode')
      if (fromIntent) {
        sessionStorage.removeItem('workbench_home_intent')
        if (fromHome) {
          const key = typeof fromIntent === 'string' ? fromIntent.trim() : ''
          homeIntentHint.value = INTENT_FROM_HOME[key] || ''
        }
      }
      if (fromLlm) {
        sessionStorage.removeItem('workbench_home_llm')
        if (fromLlmMode) sessionStorage.removeItem('workbench_home_llm_mode')
        try {
          const o = JSON.parse(fromLlm)
          const prov = typeof o.provider === 'string' ? o.provider.trim() : ''
          const mod = typeof o.model === 'string' ? o.model.trim() : ''
          if (prov && mod) {
            if (fromLlmMode === 'auto') {
              homeLlmHint.value = `Auto · 账户默认模型：${prov} · ${mod}`
            } else {
              homeLlmHint.value = `自选模型（已写入账户默认）：${prov} · ${mod}`
            }
          }
        } catch {
          homeLlmHint.value = ''
        }
      }
      const skipHomeModal = route.query.edit != null && String(route.query.edit).trim() !== ''
      if (fromHome && !skipHomeModal) {
        sessionStorage.removeItem('workbench_home_draft')
        newWorkflow.value.description = fromHome
        showCreateModal.value = true
        flash('已从工作台首页带入描述，请填写工作流名称后创建。', true)
      }
    } catch {
      /* ignore */
    }
  }

  watch(showCreateModal, (open) => {
    if (!open) {
      homeLlmHint.value = ''
      homeIntentHint.value = ''
    }
  })

  return { homeLlmHint, homeIntentHint, restoreHomeDraft }
}
