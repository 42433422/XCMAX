import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { DirectGeneratedFile } from '../utils/directGeneratedFiles'
import {
  planComposerAttachmentStrip,
  planHeaderGeneratedStrip,
  WB_HEADER_FILE_STRIP_MAX_VISIBLE,
} from '../utils/workbenchFileStripPlan'

/** 工作台附件在管家收纳中的最小字段（与 WorkbenchHomeView 直传附件项兼容）。 */
export type ButlerTrayAttachment = {
  id: string
  name: string
  status: string
  purpose?: string
  ingesting?: boolean
}

export type ButlerTrayActions = {
  removeAttachment?: (id: string) => void | Promise<void>
  removeGenerated?: (id: string) => void
  downloadGenerated?: (file: DirectGeneratedFile) => void | Promise<void>
}

/**
 * 同步工作台顶栏文件条带与 AI 管家收纳：超出条带配额的附件/已生成文件。
 */
export const useButlerWorkbenchTrayStore = defineStore('butlerWorkbenchTray', () => {
  const attachments = ref<ButlerTrayAttachment[]>([])
  const generated = ref<DirectGeneratedFile[]>([])
  const maxVisible = ref(WB_HEADER_FILE_STRIP_MAX_VISIBLE)
  const actions = ref<ButlerTrayActions>({})

  const stripPlan = computed(() => {
    const gen = planHeaderGeneratedStrip(generated.value.length, maxVisible.value)
    const att = planComposerAttachmentStrip(attachments.value.length)
    return {
      stripAttachmentCount: att.visibleCount,
      stripGeneratedCount: gen.stripGeneratedCount,
      overflowAttachmentCount: att.overflowCount,
      overflowGeneratedCount: gen.overflowGeneratedCount,
      overflowCount: gen.overflowCount + att.overflowCount,
    }
  })

  const stripAttachments = computed(() =>
    attachments.value.slice(0, stripPlan.value.stripAttachmentCount),
  )
  const stripGenerated = computed(() =>
    generated.value.slice(0, stripPlan.value.stripGeneratedCount),
  )
  const overflowAttachments = computed(() =>
    attachments.value.slice(stripPlan.value.stripAttachmentCount),
  )
  const overflowGenerated = computed(() =>
    generated.value.slice(stripPlan.value.stripGeneratedCount),
  )
  const overflowCount = computed(() => stripPlan.value.overflowCount)
  const hasTrayContent = computed(
    () => overflowCount.value > 0 || generated.value.length > 0 || attachments.value.length > 0,
  )

  function setWorkbenchFiles(payload: {
    attachments?: ButlerTrayAttachment[]
    generated?: DirectGeneratedFile[]
    maxVisible?: number
  }) {
    if (payload.attachments) attachments.value = payload.attachments
    if (payload.generated) generated.value = payload.generated
    if (payload.maxVisible != null) maxVisible.value = payload.maxVisible
  }

  function registerActions(next: ButlerTrayActions) {
    actions.value = { ...actions.value, ...next }
  }

  function clearActions() {
    actions.value = {}
  }

  return {
    attachments,
    generated,
    maxVisible,
    actions,
    stripPlan,
    stripAttachments,
    stripGenerated,
    overflowAttachments,
    overflowGenerated,
    overflowCount,
    hasTrayContent,
    setWorkbenchFiles,
    registerActions,
    clearActions,
  }
})
