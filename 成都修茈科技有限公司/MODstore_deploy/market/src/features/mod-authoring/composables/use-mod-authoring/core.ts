// useModAuthoring 核心共享状态：详情/摘要/AI 蓝图数据与 flash 提示（原单体实现原样迁移）。
import { ref } from 'vue'
import type { Ref } from 'vue'
import type { LooseRecord } from '../../types'
import type { ModAuthoringData, ModAuthoringSummary } from './types'

export type Flash = (msg: string, ok?: boolean, durationMs?: number) => void

export type SaveManifest = (opts?: { successMessage?: string; flashDurationMs?: number }) => Promise<void>

export interface ModAuthoringCore {
  modData: Ref<ModAuthoringData | null>
  summary: Ref<ModAuthoringSummary | null>
  aiBlueprint: Ref<LooseRecord | null>
  manifestText: Ref<string>
  manifestSaveWarnings: Ref<string[]>
  loading: Ref<boolean>
  loadError: Ref<string>
  message: Ref<string>
  messageOk: Ref<boolean>
  flash: Flash
}

export function createModAuthoringCore(): ModAuthoringCore {
  const modData = ref<ModAuthoringData | null>(null)
  const summary = ref<ModAuthoringSummary | null>(null)
  const aiBlueprint = ref<LooseRecord | null>(null)
  const manifestText = ref('')
  const manifestSaveWarnings = ref<string[]>([])
  const loading = ref(true)
  const loadError = ref('')
  const message = ref('')
  const messageOk = ref(true)

  let flashTimer: ReturnType<typeof setTimeout> | null = null

  function flash(msg: string, ok = true, durationMs = 5000) {
    if (flashTimer) clearTimeout(flashTimer)
    message.value = msg
    messageOk.value = ok
    flashTimer = setTimeout(() => {
      message.value = ''
      flashTimer = null
    }, durationMs)
  }

  return { modData, summary, aiBlueprint, manifestText, manifestSaveWarnings, loading, loadError, message, messageOk, flash }
}
