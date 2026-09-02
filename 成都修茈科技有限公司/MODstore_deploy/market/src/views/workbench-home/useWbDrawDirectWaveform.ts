import { type ComputedRef, type Ref, ref, computed, onUnmounted, nextTick, watch } from 'vue'
import { useSpeechRecognition } from '../../composables/useSpeechRecognition'
import { executeVoiceBargeIn } from '../../composables/voiceBargeIn'
import { isVoiceSpeculativeFiller } from '../../composables/voiceSpeculativeFiller'
import { createVoiceWorkbenchState } from '../../composables/useVoiceWorkbench'
import { appendCoalescedVoiceUserTurn } from '../../composables/voiceUserTurnCoalesce'
import type { VoiceTurnMessage } from '../../composables/voiceUserTurnCoalesce'
import { sanitizeVoiceUtteranceText, createDefaultVoiceSessionState } from '../../composables/voiceSessionAgent'
import { inlineVoiceAriaLabel, inlineVoiceStatusLabel, resolveInlineVoicePhase } from '../../composables/inlineVoiceUi'
import { directFileExt, directFileKind, directFileKindLabel, formatDirectFileSize, resolveReadEmployeeForExtension } from '../../utils/directAttachments'
import type { DirectAttachmentKind } from '../../utils/directAttachments'
import { employeeAcceptsFileExtension, isGenerateEmployeeId, readEmployeeDisplayName } from '../../utils/tabularReadEmployees'
import { starterRequiresAttachment } from '../../utils/officeEmployeeOrchestration'
import type { useWbSuggestModIdFromText } from './useWbSuggestModIdFromText'
import type { DirectAttachment, WorkbenchStateRecord } from './types'

// 拆分自 WorkbenchHomeView.vue（原行 2877–2904, 3071–3080, 3082–3091 …）；逐字迁移，行为不变。
export function useWbDrawDirectWaveform(ctx: ReturnType<typeof useWbSuggestModIdFromText>) {
  const {
    wbSidebar, wbNav, inputRef, orchestrationSession, __wbState, planSession,
    composerIntent, directDraft, directFileInputRef, directAttachedFiles, directLoading, directError,
    directVoiceListening, directVoiceAudioLevel, directWaveformCanvas, makeVoiceListening, directVoiceRecognizing, makeVoiceRecognizing,
    directVoicePermissionHint, makeVoicePermissionHint, WB_DIRECT_CHAT_EMPLOYEE_ID_KEY, directChatEmployeeId, directImageGenEnabled, directVideoGenEnabled,
    personalSettings, streamingTts, voiceS2s, voiceUnified, voiceUseUnified, voiceUseS2S,
    showMediaGen, CONSUMPTION_TIER_STORAGE_KEY, consumptionTier, tierPanelOpen, empPanelOpen, updateTierPanelAnchor,
    updateEmpPanelAnchor,
  } = ctx

const directAttachHint = computed(() => {
  const list = directAttachedFiles.value
  if (!list.length) return ''
  const empReady = list.filter((f) => f.purpose === 'employee' && f.status === 'ready').length
  const visionReady = list.filter((f) => f.purpose === 'vision' && f.status === 'ready').length
  const ready = list.filter((f) => f.purpose !== 'employee' && f.purpose !== 'vision' && f.status === 'ready').length
  const uploading = list.filter((f) => f.status === 'uploading').length
  const inlined = list.filter((f) => f.purpose !== 'employee' && f.purpose !== 'vision' && f.status === 'inline').length
  const skipped = list.filter((f) => f.status === 'skipped').length
  const errored = list.filter((f) => f.status === 'error').length
  const parts: string[] = []
  if (uploading) parts.push(`${uploading} 个读取中`)
  if (empReady) parts.push(`${empReady} 个将由读取员工全量解析（发送时直传原文件）`)
  if (visionReady) parts.push(`${visionReady} 张图片将发给视觉模型识别`)
  if (ready) parts.push(`${ready} 个已纳入资料库（提问时按相关度自动召回）`)
  if (inlined) parts.push(`${inlined} 个已读取，可直接发送给模型`)
  const embLabels = Array.from(
    new Set(
      list
        .map((f) => formatEmbeddingLabel(f.embedding))
        .filter(Boolean),
    ),
  )
  if (embLabels.length) parts.push(`向量索引：${embLabels.join('、')}`)
  if (skipped) parts.push(`${skipped} 个未受支持，仅附文件名给模型参考`)
  if (errored) parts.push(`${errored} 个上传失败，仅附文件名给模型参考`)
  return parts.join(' · ')
})
function toggleDirectImageGen() {
  const next = !directImageGenEnabled.value
  directImageGenEnabled.value = next
  if (next) {
    directVideoGenEnabled.value = false
    showMediaGen.value = false
  }
  tierPanelOpen.value = false
  empPanelOpen.value = false
}
function toggleDirectVideoGen() {
  const next = !directVideoGenEnabled.value
  directVideoGenEnabled.value = next
  if (next) {
    directImageGenEnabled.value = false
    showMediaGen.value = false
  }
  tierPanelOpen.value = false
  empPanelOpen.value = false
}
function toggleEmpPanel() {
  const next = !empPanelOpen.value
  empPanelOpen.value = next
  if (next) {
    tierPanelOpen.value = false
    nextTick(() => updateEmpPanelAnchor())
  }
}
function applyStarterPrompt(prompt: string, opts?: { requiresAttachment?: boolean; label?: string }) {
  directDraft.value = prompt
  const needsAttach =
    opts?.requiresAttachment === true ||
    (opts?.label ? starterRequiresAttachment(opts.label) : false)
  const hasOfficeAttach = directAttachedFiles.value.some(
    (f) => f.purpose === 'employee' && f.status === 'ready',
  )
  if (needsAttach && !hasOfficeAttach) {
    directError.value = '请先点击「添加附件」上传文档或表格，再发送。平台将用办公读取员工真实解析，不会凭空编造文件内容。'
    nextTick(() => {
      openDirectFilePicker()
      inputRef.value?.focus()
    })
    return
  }
  directError.value = ''
  nextTick(() => inputRef.value?.focus())
}
function onScenePanelOutside(e: MouseEvent) {
  const el = e.target as HTMLElement | null
  if (!el?.closest) return
  if (el.closest('.wb-scene-panel') || el.closest('.wb-scene-toolbar-btn')) return
  tierPanelOpen.value = false
  empPanelOpen.value = false
}
function onScenePanelKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  tierPanelOpen.value = false
  empPanelOpen.value = false
}
function onScenePanelReposition() {
  if (tierPanelOpen.value) updateTierPanelAnchor()
  if (empPanelOpen.value) updateEmpPanelAnchor()
}
const titleEnterDone = ref(false)
const composerPanelEnter = ref(true)
const contentEnter = ref(true)
const directBoxEnter = ref(true)
function useTypewriter(source: Ref<string> | ComputedRef<string>, speed = 55, resetTrigger?: ComputedRef<unknown>) {
  const displayed = ref('')
  const isTyping = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null
  function typeChar(text: string, pos: number) {
    if (pos <= text.length) {
      displayed.value = text.slice(0, pos)
      isTyping.value = pos < text.length
      timer = setTimeout(typeChar, speed, text, pos + 1)
    } else {
      isTyping.value = false
    }
  }
  function startTyping(text: string) {
    if (timer) clearTimeout(timer)
    if (!text) { displayed.value = ''; isTyping.value = false; return }
    displayed.value = ''
    timer = setTimeout(typeChar, 120, text, 0)
  }
  watch(source, v => startTyping(v), { immediate: true })
  if (resetTrigger) watch(resetTrigger, () => startTyping(source.value))
  onUnmounted(() => { if (timer) clearTimeout(timer) })
  return { displayed, isTyping }
}
const directAttachExpanded = ref(false)
const convPopoverOpen = ref(false)
watch(consumptionTier, (v) => {
  try {
    sessionStorage.setItem(CONSUMPTION_TIER_STORAGE_KEY, String(v))
  } catch {
    /* ignore */
  }
})
const voiceMessages = ref<VoiceTurnMessage[]>([])
const voiceSessionState = ref(createDefaultVoiceSessionState('employee'))
const voiceError = ref('')
const voiceMicFallbackHint = ref('')
const voiceState = ref('idle')
const voiceReport = ref('')
const waveformCanvas = ref<HTMLCanvasElement | null>(null)
const voiceWorkbench = createVoiceWorkbenchState()
const {
  voiceChatPhase,
  voiceWorkPhase,
  voiceChatBusy,
  voiceInjectQueue,
  syncWorkPhase,
  pushInject,
  clearInjectQueue,
} = voiceWorkbench
const VOICE_TTS_FEED_OPTS = {
  minLen: 8,
  earlyClause: true,
  earlyClauseMinLen: 10,
  browserLeadIn: true,
}
const voiceAutoSend = computed(() => wbSidebar.activeMode === 'voice')
// 声波可视化绘制
const WAVE_BAR_COUNT = 40
const waveBarHeights = new Float32Array(WAVE_BAR_COUNT).fill(2)
const directWaveBarHeights = new Float32Array(WAVE_BAR_COUNT).fill(2)
function drawDirectWaveform() {
  const canvas = directWaveformCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const dpr = window.devicePixelRatio || 1
  const w = canvas.clientWidth
  const h = canvas.clientHeight
  canvas.width = w * dpr
  canvas.height = h * dpr
  ctx.scale(dpr, dpr)
  ctx.clearRect(0, 0, w, h)
  const level = directVoiceAudioLevel.value < 0.03 ? 0 : directVoiceAudioLevel.value
  const barW = Math.max(2, (w / WAVE_BAR_COUNT) - 2)
  const gap = 2
  const maxH = h - 2
  for (let i = 0; i < WAVE_BAR_COUNT; i++) {
    const center = WAVE_BAR_COUNT / 2
    const dist = Math.abs(i - center) / center
    const envelope = 1 - dist * dist
    const target = 2 + level * envelope * maxH * (0.6 + 0.4 * Math.sin(Date.now() / 150 + i * 0.7))
    directWaveBarHeights[i] += (target - directWaveBarHeights[i]) * 0.3
    const bh = Math.max(2, directWaveBarHeights[i])
    const x = i * (barW + gap) + gap
    const y = (h - bh) / 2
    const alpha = 0.3 + level * 0.5 * envelope
    ctx.fillStyle = `rgba(129,140,248,${alpha})`
    ctx.beginPath()
    ctx.roundRect(x, y, barW, bh, 1.5)
    ctx.fill()
  }
  __wbState.directWaveRafId = requestAnimationFrame(drawDirectWaveform)
}
watch(directVoiceListening, (v) => {
  if (v && wbNav.isMobile) {
    directWaveBarHeights.fill(2)
    nextTick(() => { __wbState.directWaveRafId = requestAnimationFrame(drawDirectWaveform) })
  } else {
    cancelAnimationFrame(__wbState.directWaveRafId)
    directVoiceAudioLevel.value = 0
  }
})
const voiceProgress = computed(() => {
  const steps = Array.isArray(orchestrationSession.value?.steps) ? orchestrationSession.value.steps : []
  if (!steps.length) return 0
  const done = steps.filter((s) => s.status === 'done').length
  const running = steps.some((s) => s.status === 'running') ? 0.45 : 0
  return Math.min(100, Math.round(((done + running) / steps.length) * 100))
})
const inlineAsr = useSpeechRecognition()
const directVoicePhase = computed(() =>
  resolveInlineVoicePhase(
    directVoiceListening.value,
    directVoiceRecognizing.value,
    directVoicePermissionHint.value,
  ),
)
const makeVoicePhase = computed(() =>
  resolveInlineVoicePhase(
    makeVoiceListening.value,
    makeVoiceRecognizing.value,
    makeVoicePermissionHint.value,
  ),
)
const directVoiceBtnClass = computed(() => ({
  'wb-direct-voice-btn--recording': directVoicePhase.value === 'recording',
  'wb-direct-voice-btn--recognizing': directVoicePhase.value === 'recognizing',
  'wb-direct-voice-btn--permission': directVoicePhase.value === 'permission',
  'wb-direct-voice-btn--on':
    directVoicePhase.value === 'recording' || directVoicePhase.value === 'recognizing',
  'wb-direct-voice-btn--ptt': wbNav.isMobile,
}))
const makeVoiceBtnClass = computed(() => ({
  'wb-direct-voice-btn--recording': makeVoicePhase.value === 'recording',
  'wb-direct-voice-btn--recognizing': makeVoicePhase.value === 'recognizing',
  'wb-direct-voice-btn--permission': makeVoicePhase.value === 'permission',
  'wb-direct-voice-btn--on':
    makeVoicePhase.value === 'recording' || makeVoicePhase.value === 'recognizing',
}))
const directVoiceAria = computed(() =>
  inlineVoiceAriaLabel(directVoicePhase.value, wbNav.isMobile, __wbState.inlineHoldCancelIntent),
)
const makeVoiceAria = computed(() => inlineVoiceAriaLabel(makeVoicePhase.value, false, false))
const directVoiceStatusText = computed(() =>
  inlineVoiceStatusLabel(
    directVoicePhase.value,
    wbNav.isMobile,
    __wbState.inlineHoldCancelIntent,
    directVoicePermissionHint.value,
    inlineAsr.loadingHint.value,
  ),
)
const makeVoiceStatusText = computed(() =>
  inlineVoiceStatusLabel(
    makeVoicePhase.value,
    false,
    false,
    makeVoicePermissionHint.value,
    inlineAsr.loadingHint.value,
  ),
)
const directVoiceCanCancel = computed(
  () => directVoicePhase.value === 'recording' || directVoicePhase.value === 'recognizing',
)
const makeVoiceCanCancel = computed(
  () => makeVoicePhase.value === 'recording' || makeVoicePhase.value === 'recognizing',
)
function canSpeculateForPartial(partialText: string): boolean {
  if (voiceUseUnified.value || voiceUseS2S.value) return false
  if (personalSettings.value.voiceSpeechMode !== 'cascade') return false
  const t = partialText.trim()
  if (t.length < 12) return false
  if (isVoiceSpeculativeFiller(t)) return false
  return true
}
function appendVoiceUserTurn(text: string) {
  const trimmed = sanitizeVoiceUtteranceText(text)
  if (!trimmed) return
  voiceMessages.value = appendCoalescedVoiceUserTurn(voiceMessages.value, trimmed)
}
function phoneTurnTextDelta(assistantIdx: number) {
  return (_d: string, soFar: string) => {
    const msgs = [...voiceMessages.value]
    if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: soFar }
    voiceMessages.value = msgs
    voiceReport.value = soFar
  }
}
function cancelSpeculativeVoiceTurn() {
  __wbState.voiceStreamHandle?.abort()
  __wbState.voiceStreamHandle = null
  if (voiceChatBusy.value) {
    voiceChatBusy.value = false
    voiceChatPhase.value = 'idle'
    voiceState.value = 'idle'
    const msgs = [...voiceMessages.value]
    const last = msgs[msgs.length - 1]
    if (last?.role === 'assistant' && !last.content) {
      msgs.pop()
      voiceMessages.value = msgs
    }
    voiceReport.value = ''
    streamingTts.stop()
  }
}
function triggerVoiceBargeIn() {
  if (!voiceAutoSend.value) return
  executeVoiceBargeIn({
    stopS2s: () => {
      voiceS2s.cancelTurn()
      voiceUnified.cancelTurn()
      __wbState.s2sProvisionalStarted = false
    },
    stopCascadeTts: () => streamingTts.stop(),
    abortLlmStream: () => {
      __wbState.voiceStreamHandle?.abort()
      __wbState.voiceStreamHandle = null
    },
    setIdle: () => {
      voiceChatBusy.value = false
      voiceChatPhase.value = 'idle'
      voiceState.value = 'idle'
    },
  })
}
/** 波形区：聆听中或 ASR 重连/切换方案时保持可见，避免 v-if 闪灭 */
const voiceAssistantSpeaking = computed(
  () =>
    voiceUseUnified.value
      ? voiceUnified.isPlaying() || voiceUnified.state.value === 'speaking' || voiceUnified.state.value === 'streaming'
      : voiceUseS2S.value
        ? voiceS2s.isPlaying() || voiceS2s.state.value === 'streaming' || voiceS2s.state.value === 'speaking'
        : streamingTts.state.value !== 'idle',
)
const voiceHasAssistantContent = computed(() =>
  voiceMessages.value.some((m) => m.role === 'assistant' && String(m.content || '').trim()),
)
const voiceTitle = computed(() => {
  if (composerIntent.value === 'employee') {
    const ps = planSession.value
    if (ps) {
      if (ps.phase === 'summary') {
        return ps.summaryNeedsClarification ? '还需补充信息' : '摘要确认'
      }
      if (ps.phase === 'chat') return '需求澄清'
      if (ps.phase === 'checklist') return '执行清单'
      if (ps.phase === 'done') return '规划完成'
    }
    const stage = voiceSessionState.value.stage
    if (stage === 'clarifying') return '正在理解需求'
    if (stage === 'ready_to_plan') return '可以开始规划'
    if (stage === 'executing') return '制作中'
  }
  if (voiceState.value === 'listening') return '我在听'
  if (voiceState.value === 'processing') return '正在处理'
  if (voiceState.value === 'reporting') return '汇报中'
  return '说出你想制作的东西'
})
function directFileChipTitle(f: DirectAttachment | null | undefined): string {
  if (!f) return ''
  const emb = formatEmbeddingLabel(f.embedding)
  if (f.purpose === 'vision') {
    if (f.status === 'uploading') return `${f.name}：正在压缩图片，准备随本轮问题发给视觉模型…`
    if (f.status === 'ready') return `${f.name}：已压缩，将随本轮问题发给视觉模型识别`
    if (f.status === 'error') return `${f.name}：${f.error || '图片处理失败'}`
  }
  if (f.status === 'uploading') return `${f.name}：正在读取文件内容…`
  if (f.status === 'ready') return `${f.name}：已纳入资料库，提问时会按相关度自动召回片段${emb ? `；向量模型：${emb}` : ''}`
  if (f.status === 'inline') {
    return f.ingestError
      ? `${f.name}：已读取文本，可直接发送；${f.ingestError}`
      : `${f.name}：已读取文本，将直接注入模型上下文${f.ingesting ? '，资料库入库中' : ''}${emb ? `；向量模型：${emb}` : ''}`
  }
  if (f.status === 'skipped') return `${f.name}：${f.error || '该格式暂不解析；将仅附文件名供模型参考'}`
  if (f.status === 'error') return `${f.name}：${f.error || '上传失败'}（仅附文件名给模型参考）`
  return f.name
}
function formatEmbeddingLabel(embedding: WorkbenchStateRecord | null | undefined): string {
  if (!embedding || typeof embedding !== 'object') return ''
  const provider = String(embedding.provider || '').trim()
  const model = String(embedding.model || '').trim()
  const dim = Number(embedding.dim || 0) || 0
  if (!provider && !model) return ''
  return `${provider || '默认'} / ${model || '默认模型'}${dim ? ` · ${dim}维` : ''}`
}
function directAttachmentKind(f: DirectAttachment | null | undefined): DirectAttachmentKind {
  return directFileKind(f?.name || '', f?.file?.type || '')
}
function directAttachmentKindLabel(f: DirectAttachment | null | undefined): string {
  return directFileKindLabel(directAttachmentKind(f))
}
function directAttachmentStatusText(f: DirectAttachment | null | undefined): string {
  if (!f) return ''
  if (f.purpose === 'vision') {
    if (f.status === 'uploading') return '压缩中'
    if (f.status === 'ready') return '待识图'
    if (f.status === 'error') return '处理失败'
  }
  if (f.status === 'uploading') return '读取中'
  if (f.status === 'ready') return f.embedding ? '已入库 · 向量' : '已入库'
  if (f.status === 'inline') {
    if (f.ingesting) return '可发送 · 入库中'
    if (f.ingestError) return '可发送 · 入库失败'
    return '可发送'
  }
  if (f.status === 'skipped') return '未支持'
  return '读取失败'
}
function directAttachmentNote(files: DirectAttachment[] | null | undefined): string {
  const list = Array.isArray(files) ? files : []
  if (!list.length) return ''
  const parts = list.map((f, idx) => {
    let tag =
      f.status === 'ready'
        ? '已入库'
        : f.status === 'uploading'
          ? '读取中'
          : f.status === 'inline'
            ? '已读取'
            : f.status === 'error'
              ? '上传失败'
              : '未解析'
    if (f.purpose === 'employee' && f.status === 'ready') {
      const emp = String(f.readEmployeeId || resolveReadEmployeeForExtension(directFileExt(f.name)) || '').trim()
      tag = emp ? `读取员工·${readEmployeeDisplayName(emp)}` : '读取员工'
    } else if (f.purpose === 'vision' && f.status === 'ready') {
      tag = '识图图片'
    } else if (f.purpose === 'vision' && f.status === 'uploading') {
      tag = '图片压缩中'
    }
    return `@附件${idx + 1} ${f.name}（${formatDirectFileSize(f.size)}，${tag}）`
  })
  return `[附件顺序：${parts.join('，')}]`
}
function resolveDirectFileEmployeeId(f: { readEmployeeId?: string; name?: string }): string {
  const ext = directFileExt(String(f.name || ''))
  const fromExt = resolveReadEmployeeForExtension(ext)
  if (fromExt) return fromExt
  const fromItem = String(f.readEmployeeId || '').trim()
  if (fromItem && !isGenerateEmployeeId(fromItem) && employeeAcceptsFileExtension(fromItem, ext)) {
    return fromItem
  }
  const picked = String(directChatEmployeeId.value || '').trim()
  if (picked && !isGenerateEmployeeId(picked) && employeeAcceptsFileExtension(picked, ext)) {
    return picked
  }
  return ''
}
function applyDirectReadEmployeePick(readEmployeeId: string) {
  const id = String(readEmployeeId || '').trim()
  if (!id) return
  directChatEmployeeId.value = id
  try {
    sessionStorage.setItem(WB_DIRECT_CHAT_EMPLOYEE_ID_KEY, id)
  } catch {
    /* ignore */
  }
}
function openDirectFilePicker() {
  if (directLoading.value) return
  directFileInputRef.value?.click?.()
}
function makeDirectAttachId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    try {
      return crypto.randomUUID()
    } catch {
      /* fallthrough */
    }
  }
  return `att_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

  return {
    ...ctx, directAttachHint, toggleDirectImageGen, toggleDirectVideoGen, toggleEmpPanel,
    applyStarterPrompt, onScenePanelOutside, onScenePanelKeydown, onScenePanelReposition, titleEnterDone,
    composerPanelEnter, contentEnter, directBoxEnter, useTypewriter, directAttachExpanded,
    convPopoverOpen, voiceMessages, voiceSessionState, voiceError, voiceMicFallbackHint,
    voiceState, voiceReport, waveformCanvas, voiceWorkbench, voiceChatPhase,
    voiceWorkPhase, voiceChatBusy, voiceInjectQueue, syncWorkPhase, pushInject,
    clearInjectQueue, VOICE_TTS_FEED_OPTS, voiceAutoSend, WAVE_BAR_COUNT, waveBarHeights,
    directWaveBarHeights, drawDirectWaveform, voiceProgress, inlineAsr, directVoicePhase,
    makeVoicePhase, directVoiceBtnClass, makeVoiceBtnClass, directVoiceAria, makeVoiceAria,
    directVoiceStatusText, makeVoiceStatusText, directVoiceCanCancel, makeVoiceCanCancel, canSpeculateForPartial,
    appendVoiceUserTurn, phoneTurnTextDelta, cancelSpeculativeVoiceTurn, triggerVoiceBargeIn, voiceAssistantSpeaking,
    voiceHasAssistantContent, voiceTitle, directFileChipTitle, formatEmbeddingLabel, directAttachmentKind,
    directAttachmentKindLabel, directAttachmentStatusText, directAttachmentNote, resolveDirectFileEmployeeId, applyDirectReadEmployeePick,
    openDirectFilePicker, makeDirectAttachId,
  }
}

export type useWbDrawDirectWaveformBinds = ReturnType<typeof useWbDrawDirectWaveform>
