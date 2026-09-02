import { computed, ref, type ComputedRef, type WritableComputedRef } from 'vue'
import { api } from '../api'
import type { useFieldAi } from './useFieldAi'
import { useStreamingTts } from './useStreamingTts'
import {
  DEFAULT_MODULE_ORDER,
  MODULE_META,
  addModuleToManifest,
  type EmployeeModuleKind,
} from './useWorkbenchManifest'
import type { useWorkbenchStore } from '../stores/workbench'

type WorkbenchStore = ReturnType<typeof useWorkbenchStore>
type FieldAi = ReturnType<typeof useFieldAi>

/** RightRail 交互域：AI 优化提示词、研究上下文、试运行、TTS 试听、模块库（自 RightRail.vue 原样迁移） */
export function useRightRailActions(deps: {
  store: WorkbenchStore
  fieldAi: FieldAi
  manifest: ComputedRef<Record<string, unknown>>
  getPath: (path: string) => unknown
  setPath: (path: string, value: unknown) => void
  systemPrompt: WritableComputedRef<string>
  roleName: WritableComputedRef<string>
}) {
  const { store, fieldAi, manifest, getPath, systemPrompt, roleName } = deps

  // ── Refine prompt with AI ───────────────────────────────────────────────────

  const refineInstruction = ref('请使提示词更专业、更清晰、更具引导性')
  const refineResult = ref('')
  const refineExplanation = ref('')
  const refineLoading = ref(false)

  async function refinePrompt() {
    if (!systemPrompt.value.trim()) return
    refineLoading.value = true
    const result = await fieldAi.assist('refine-prompt', systemPrompt.value, {
      roleContext: roleName.value,
      instruction: refineInstruction.value,
    })
    refineLoading.value = false
    if (result) {
      refineResult.value = result.value
      refineExplanation.value = result.explanation ?? ''
    }
  }

  function applyRefine() {
    if (!refineResult.value) return
    systemPrompt.value = refineResult.value
    refineResult.value = ''
    refineExplanation.value = ''
  }

  // ── Research context for workflow selection ─────────────────────────────────

  const researchBrief = ref('')
  const researchLoading = ref(false)

  async function fetchResearch() {
    const brief = researchBrief.value.trim() || store.target.name
    if (!brief) return
    researchLoading.value = true
    try {
      const res = await api.workbenchResearchContext?.(brief) as Record<string, unknown> | undefined
      if (res) {
        store.setResearch(String(res.context ?? ''), Array.isArray(res.sources) ? res.sources as string[] : [])
      }
    } catch { /* ignore */ }
    finally { researchLoading.value = false }
  }

  // ── Run (execute) section ─────────────────────────────────────────────────

  const runInput = ref('')
  const runResult = ref<string | null>(null)
  const runLoading = ref(false)

  async function runEmployee() {
    const eid = store.target.id
    if (!eid) {
      runResult.value = '请先保存员工（需要 ID）'
      return
    }
    runLoading.value = true
    runResult.value = null
    try {
      const res = await api.executeEmployeeTask(eid, runInput.value, {}) as Record<string, unknown>
      runResult.value = JSON.stringify(res, null, 2)
    } catch (e: unknown) {
      runResult.value = `错误: ${(e as Error)?.message || String(e)}`
    } finally {
      runLoading.value = false
    }
  }

  // ── TTS preview ────────────────────────────────────────────────────────────

  const ttsText = ref('')
  const ttsLoading = ref(false)

  const streamingTts = useStreamingTts(() => ({
    engine: 'edge-online',
    edgeVoice: 'zh-CN-XiaoxiaoNeural',
    browserVoiceName: '',
    rate: 1,
  }))

  async function previewTts() {
    const text = ttsText.value.trim() || '你好，我是您的 AI 助理'
    ttsLoading.value = true
    try {
      await streamingTts.speak(text)
    } catch { /* ignore */ }
    finally { ttsLoading.value = false }
  }

  // ── Module library ─────────────────────────────────────────────────────────

  const presentModuleKinds = computed(() => {
    const _m = manifest.value
    return new Set(
      DEFAULT_MODULE_ORDER.filter((kind) => {
        if (MODULE_META[kind].required) return true
        const meta = MODULE_META[kind]
        return meta.paths.some((p) => {
          const val = getPath(p)
          return val != null
        })
      }),
    )
  })

  function addModule(kind: EmployeeModuleKind) {
    store.target.manifest = addModuleToManifest(
      manifest.value,
      kind,
    ) as Record<string, unknown>
    store.dirty = true
  }

  function dragModuleStart(kind: EmployeeModuleKind, event: DragEvent) {
    event.dataTransfer?.setData('application/emp-module-kind', kind)
  }

  return {
    refineInstruction,
    refineResult,
    refineExplanation,
    refineLoading,
    refinePrompt,
    applyRefine,
    researchBrief,
    researchLoading,
    fetchResearch,
    runInput,
    runResult,
    runLoading,
    runEmployee,
    ttsText,
    ttsLoading,
    previewTts,
    presentModuleKinds,
    addModule,
    dragModuleStart,
  }
}

export type RightRailActionsApi = ReturnType<typeof useRightRailActions>
