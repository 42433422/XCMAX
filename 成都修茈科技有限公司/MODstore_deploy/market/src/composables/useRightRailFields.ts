import { computed } from 'vue'
import { STATIC_DEFAULT_EMPLOYEE_LLM } from '../domain/llm/defaultEmployeeLlm'
import type { EmployeeNodeData } from './useWorkbenchManifest'
import type { useWorkbenchStore } from '../stores/workbench'

type WorkbenchStore = ReturnType<typeof useWorkbenchStore>

/** RightRail 属性面板：manifest 读写与身份 / 提示词 / 模型等字段的 computed 绑定（自 RightRail.vue 原样迁移） */
export function useRightRailFields(deps: { store: WorkbenchStore }) {
  const { store } = deps

  // ── Inspector mode computed ─────────────────────────────────────────────────

  const mode = computed(() => store.inspectorMode)

  const selectedNodeData = computed<EmployeeNodeData | null>(() => {
    const node = store.selectedNode
    if (!node) return null
    return node.data as EmployeeNodeData
  })

  // ── Local field edits (bound to manifest slice) ─────────────────────────────

  const manifest = computed(() => store.target.manifest as Record<string, unknown>)

  function getPath(path: string): unknown {
    return path.split('.').reduce<unknown>((cur, key) => {
      if (cur == null || typeof cur !== 'object') return undefined
      return (cur as Record<string, unknown>)[key]
    }, manifest.value)
  }

  function setPath(path: string, value: unknown) {
    store.patchManifest(path, value)
  }

  // ── Identity fields ─────────────────────────────────────────────────────────

  const identityName = computed({
    get: () => String(getPath('identity.name') ?? ''),
    set: (v) => setPath('identity.name', v),
  })

  const identityId = computed({
    get: () => String(getPath('identity.id') ?? ''),
    set: (v) => setPath('identity.id', v),
  })

  const identityVersion = computed({
    get: () => String(getPath('identity.version') ?? '1.0.0'),
    set: (v) => setPath('identity.version', v),
  })

  const identityDesc = computed({
    get: () => String(getPath('identity.description') ?? ''),
    set: (v) => setPath('identity.description', v),
  })

  // ── Prompt / cognition fields ───────────────────────────────────────────────

  const systemPrompt = computed({
    get: () => String(getPath('cognition.agent.system_prompt') ?? ''),
    set: (v) => setPath('cognition.agent.system_prompt', v),
  })

  const roleName = computed({
    get: () => String(getPath('cognition.agent.role.name') ?? ''),
    set: (v) => setPath('cognition.agent.role.name', v),
  })

  const rolePersona = computed({
    get: () => String(getPath('cognition.agent.role.persona') ?? ''),
    set: (v) => setPath('cognition.agent.role.persona', v),
  })

  const roleTone = computed({
    get: () => String(getPath('cognition.agent.role.tone') ?? 'professional'),
    set: (v) => setPath('cognition.agent.role.tone', v),
  })

  const modelProvider = computed({
    get: () =>
      String(getPath('cognition.agent.model.provider') ?? STATIC_DEFAULT_EMPLOYEE_LLM.provider),
    set: (v) => setPath('cognition.agent.model.provider', v),
  })

  const modelName = computed({
    get: () =>
      String(getPath('cognition.agent.model.model_name') ?? STATIC_DEFAULT_EMPLOYEE_LLM.model_name),
    set: (v) => setPath('cognition.agent.model.model_name', v),
  })

  const temperature = computed({
    get: () => Number(getPath('cognition.agent.model.temperature') ?? 0.7),
    set: (v) => setPath('cognition.agent.model.temperature', Number(v)),
  })

  // ── Workflow heart field ────────────────────────────────────────────────────

  const workflowId = computed({
    get: () => Number(getPath('collaboration.workflow.workflow_id') ?? 0),
    set: (v) => setPath('collaboration.workflow.workflow_id', Number(v)),
  })

  // ── Skills ─────────────────────────────────────────────────────────────────

  const skills = computed(() => {
    const arr = getPath('cognition.skills')
    return Array.isArray(arr) ? arr as Array<Record<string, unknown>> : []
  })

  return {
    mode,
    selectedNodeData,
    manifest,
    getPath,
    setPath,
    identityName,
    identityId,
    identityVersion,
    identityDesc,
    systemPrompt,
    roleName,
    rolePersona,
    roleTone,
    modelProvider,
    modelName,
    temperature,
    workflowId,
    skills,
  }
}

export type RightRailFieldsApi = ReturnType<typeof useRightRailFields>
