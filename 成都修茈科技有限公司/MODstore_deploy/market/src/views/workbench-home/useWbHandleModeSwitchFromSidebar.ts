import { computed, onMounted, onActivated, onDeactivated, onUnmounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { parseWbGearQuery } from '../../domain/clientWorkshops'
import { readPlatformChatModePreference } from '../../utils/workbenchPlatformChatMode'
import { loadActiveBotId } from '../../utils/agentBots'
import { loadPersonalSettings, applyThemeToDocument } from '../../utils/personalSettings'
import { api } from '../../api'
import { getAccessToken } from '../../infrastructure/storage/tokenStore'
import { loadConversations, loadActiveId, saveActiveId, mergeConversationsForPick } from '../../utils/conversationStore'
import { unlockVoiceAudioPlayback } from '../../composables/voiceDevice'
import type { useWbHandleVoicePlanReplySmart } from './useWbHandleVoicePlanReplySmart'

// 拆分自 WorkbenchHomeView.vue（原行 8567–8573, 8587–8590, 8592–8594 …）；逐字迁移，行为不变。
export function useWbHandleModeSwitchFromSidebar(ctx: ReturnType<typeof useWbHandleVoicePlanReplySmart>) {
  const {
    route, wbSidebar, wbNav, draft, displayName, pendingHandoff,
    finalizeLoading, finalizeError, orchestrationSession, orchestrationSessionId, pollStop, orchPhase,
    orchestrationEtaSeconds, orchestrationEtaReason, __wbState, orchTimingStartMs, workflowLinkOffer, planSession,
    planReplyDraft, planOptionSelections, planOptionOtherText, clearPlanOptionOtherText, planLoadingStepsSummary, planLoadingStepsChat,
    planLoadingAdvance, CANVAS_SKILL_INTENT, composerIntent, modFrontendEnabled, activeGear, platformChatMode,
    voiceCasualChatMode, enablePlatformChatMode, disablePlatformChatMode, directVoiceListening, currentThemeIsLight, makeVoiceListening,
    directVoiceRecognizing, makeVoiceRecognizing, WB_DIRECT_CHAT_EMPLOYEE_ID_KEY, WB_DIRECT_WEB_SEARCH_KEY, WB_DIRECT_IMAGE_GEN_KEY, WB_DIRECT_VIDEO_GEN_KEY,
    directChatEmployeeId, directWebSearchEnabled, directImageGenEnabled, directVideoGenEnabled, directImageSize, directImageStyle,
    directImageCount, directVideoAspect, directVideoDurationSec, conversations, activeConversationId, directMessages,
    personalSettings, streamingTts, voiceS2s, voiceUsePhonePipeline, activeBotId, stopDirectTtsPlayback,
    butlerTrayStore, tierPanelOpen, empPanelOpen, updateTierPanelAnchor, updateEmpPanelAnchor, onScenePanelOutside,
    onScenePanelKeydown, onScenePanelReposition, titleEnterDone, composerPanelEnter, contentEnter, directBoxEnter,
    useTypewriter, voiceError, voiceState, voiceChat, voiceListening, voiceMicPausedByUser,
    voiceStatusText, removeDirectGeneratedFile, downloadGeneratedOutput, removeDirectAttachedFile, newConversationHandler, setActiveConversation,
    refreshAllBots, applyCustomerServiceRouteContext, startVoiceRecognition, stopVoiceRecognition, ensureVoiceEmployeeIntent, syncVoiceWorkPhase,
    INTENT_META, loadWorkbenchRepoPicks, stopOrchestrationElapsedTicker, loadLlmCatalogForWorkbench, onLlmDocPointerDown, onLlmEscape,
    cacheMakeProgress, restoreMakeProgressCache, cancelInlineVoice, startInlineVoice, onInlineHoldStart, stopDirectVoice,
    voiceBtnLongPressStart, stopMakeVoice, onWbOpenSettings, onWbPickConversation, activeModeReset, closePlanDiagramPreview,
    loadKnowledgeDocuments, dismissHomeBodyOverlays, openSixDimTestPreview, resumeCachedOrchestration,
  } = ctx

function onDirectVoicePointerDown(e: PointerEvent) {
  if (wbNav.isMobile) {
    onInlineHoldStart('direct', e)
    return
  }
  voiceBtnLongPressStart()
}
function onDirectVoiceClick() {
  if (wbNav.isMobile) return
  toggleDirectVoice()
}
function startDirectVoice() {
  startInlineVoice('direct')
}
function toggleDirectVoice() {
  if (__wbState.voiceBtnLongPressFired) {
    __wbState.voiceBtnLongPressFired = false
    return
  }
  if (directVoiceRecognizing.value) {
    cancelInlineVoice('direct')
    return
  }
  if (directVoiceListening.value) {
    void stopDirectVoice()
    return
  }
  void startDirectVoice()
}
function startMakeVoice() {
  startInlineVoice('make')
}
function toggleMakeVoice() {
  if (makeVoiceRecognizing.value) {
    cancelInlineVoice('make')
    return
  }
  if (makeVoiceListening.value) {
    void stopMakeVoice()
    return
  }
  void startMakeVoice()
}
function onWbNewChat() {
  newConversationHandler()
}
onMounted(async () => {
  butlerTrayStore.registerActions({
    removeAttachment: (id) => void removeDirectAttachedFile(id),
    removeGenerated: removeDirectGeneratedFile,
    downloadGenerated: (f) => void downloadGeneratedOutput(f),
  })
  setTimeout(() => {
    directBoxEnter.value = false
    composerPanelEnter.value = false
    contentEnter.value = false
  }, 30)
  document.addEventListener('pointerdown', onLlmDocPointerDown, true)
  window.addEventListener('wb-new-chat', onWbNewChat)
  window.addEventListener('wb-pick-conversation', onWbPickConversation)
  window.addEventListener('wb-open-settings', onWbOpenSettings)
  window.addEventListener('keydown', onLlmEscape)
  try {
    const pendingDraft = sessionStorage.getItem('workbench_home_pending_draft')
    const pendingIntent = sessionStorage.getItem('workbench_home_pending_intent')
    if (pendingDraft && !draft.value.trim()) draft.value = pendingDraft
    if (pendingIntent && INTENT_META[pendingIntent]) {
      composerIntent.value = pendingIntent === 'workflow' ? CANVAS_SKILL_INTENT : pendingIntent
    }
    sessionStorage.removeItem('workbench_home_pending_draft')
    sessionStorage.removeItem('workbench_home_pending_intent')
  } catch {
    /* ignore */
  }
  restoreMakeProgressCache()
  try {
    const emp = sessionStorage.getItem(WB_DIRECT_CHAT_EMPLOYEE_ID_KEY)
    if (emp && emp.trim()) directChatEmployeeId.value = emp.trim()
  } catch {
    /* ignore */
  }
  try {
    const raw = sessionStorage.getItem(WB_DIRECT_WEB_SEARCH_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { enabled?: boolean; queryDraft?: string }
      if (typeof parsed.enabled === 'boolean') directWebSearchEnabled.value = parsed.enabled
    }
  } catch {
    /* ignore */
  }
  try {
    const rawImg = sessionStorage.getItem(WB_DIRECT_IMAGE_GEN_KEY)
    if (rawImg) {
      const p = JSON.parse(rawImg) as {
        enabled?: boolean
        size?: string
        style?: string
        count?: number
      }
      if (typeof p.enabled === 'boolean') directImageGenEnabled.value = p.enabled
      if (p.size) directImageSize.value = p.size
      if (p.style) directImageStyle.value = p.style
      if (typeof p.count === 'number') directImageCount.value = p.count
    }
    const rawVid = sessionStorage.getItem(WB_DIRECT_VIDEO_GEN_KEY)
    if (rawVid) {
      const p = JSON.parse(rawVid) as {
        enabled?: boolean
        aspect?: string
        durationSec?: number
      }
      if (typeof p.enabled === 'boolean') directVideoGenEnabled.value = p.enabled
      if (p.aspect) directVideoAspect.value = p.aspect
      if (typeof p.durationSec === 'number') directVideoDurationSec.value = p.durationSec
    }
    if (directImageGenEnabled.value && directVideoGenEnabled.value) {
      directVideoGenEnabled.value = false
    }
  } catch {
    /* ignore */
  }
  /* 须在首个 await 之前完成：否则 keep-alive 下 onActivated 可能先于 bots/会话加载执行，客服深链会漏处理 */
  try {
    refreshAllBots()
    activeBotId.value = loadActiveBotId() || ''
  } catch {
    /* ignore */
  }
  try {
    conversations.value = loadConversations()
    const storedActive = loadActiveId()
    if (storedActive && conversations.value.some((c) => c.id === storedActive)) {
      activeConversationId.value = storedActive
    } else if (conversations.value.length) {
      activeConversationId.value = conversations.value[0].id
      saveActiveId(activeConversationId.value)
    }
    wbSidebar.setConversations(conversations.value)
    if (activeConversationId.value) {
      wbSidebar.setActiveConversationId(activeConversationId.value)
    }
  } catch {
    /* ignore */
  }
  try {
    applyCustomerServiceRouteContext()
  } catch {
    /* ignore */
  }

  if (getAccessToken()) {
    try {
      const me = await api.me()
      if (me && typeof me === 'object' && me.ok !== false && me.success !== false) {
        const u = typeof me.username === 'string' ? me.username.trim() : ''
        const e = typeof me.email === 'string' ? me.email.trim() : ''
        displayName.value = u || (e ? e.split('@')[0] || e : '')
      } else {
        displayName.value = ''
      }
    } catch {
      displayName.value = ''
    }
  }
  await loadLlmCatalogForWorkbench()
  await loadWorkbenchRepoPicks()
  await loadKnowledgeDocuments()

  try {
    personalSettings.value = loadPersonalSettings()
    applyThemeToDocument(personalSettings.value.theme)
    const t = personalSettings.value.theme
    currentThemeIsLight.value = t === 'light' || (t === 'auto' && window.matchMedia?.('(prefers-color-scheme: light)').matches)
  } catch {
    /* ignore */
  }
  void resumeCachedOrchestration()
})
onActivated(() => {
  window.addEventListener('wb-mode-switch', handleModeSwitchFromSidebar)
  try {
    const loaded = loadConversations()
    const aid = wbSidebar.activeConversationId || loadActiveId() || activeConversationId.value
    if (aid) {
      conversations.value = mergeConversationsForPick(
        conversations.value,
        loaded,
        aid,
        directMessages.value.length,
      )
      if (loaded.some((c) => c.id === aid)) {
        setActiveConversation(aid)
      }
    } else {
      conversations.value = loaded
    }
  } catch {
    /* ignore */
  }
  try {
    applyCustomerServiceRouteContext()
  } catch {
    /* ignore */
  }
  try {
    applyWbGearFromRoute()
  } catch {
    /* ignore */
  }
})
function applySidebarModeSideEffects(mode: 'direct' | 'make' | 'voice') {
  if (mode === 'voice') {
    enablePlatformChatMode()
    return
  }
  if (mode === 'direct') {
    voiceCasualChatMode.value = false
    platformChatMode.value = false
    return
  }
  if (mode === 'make') {
    if (readPlatformChatModePreference()) {
      enablePlatformChatMode()
      directBoxEnter.value = false
    } else {
      disablePlatformChatMode()
    }
  }
}
function handleModeSwitchFromSidebar(e: Event) {
  const mode = (e as CustomEvent).detail as 'direct' | 'make' | 'voice'
  if (!mode) return
  if (mode !== 'voice' && mode !== 'make') {
    if (planSession.value) planSession.value = null
    if (pendingHandoff.value) pendingHandoff.value = null
  }
  if (mode === 'direct') {
    composerIntent.value = CANVAS_SKILL_INTENT
  }
  applySidebarModeSideEffects(mode)
  composerPanelEnter.value = true
  contentEnter.value = true
  directBoxEnter.value = true
  titleEnterDone.value = true
  wbSidebar.setActiveMode(mode)
  activeGear.value = mode
  setTimeout(() => {
    composerPanelEnter.value = false
    titleEnterDone.value = false
    contentEnter.value = false
    // 「做」+ 平台闲聊也复用 .wb-direct-box，须结束 enter 态，否则 opacity:0 看不见输入框
    directBoxEnter.value = false
  }, 30)
}
function applyWbGearFromRoute() {
  const gear = parseWbGearQuery(route.query.wbGear)
  if (!gear) return
  handleModeSwitchFromSidebar(new CustomEvent('wb-mode-switch', { detail: gear }))
}
watch(
  () => route.query.wbGear,
  () => {
    applyWbGearFromRoute()
  },
)
onMounted(() => {
  window.addEventListener('wb-mode-switch', handleModeSwitchFromSidebar)
  applyWbGearFromRoute()
  applySidebarModeSideEffects(wbSidebar.activeMode)
  setTimeout(() => {
    directBoxEnter.value = false
    contentEnter.value = false
    composerPanelEnter.value = false
    titleEnterDone.value = false
  }, 30)
  if (wbSidebar.activeMode === 'voice' && !voiceMicPausedByUser.value && !voiceListening.value) {
    streamingTts.warmUp()
    if (!wbNav.isMobile) {
      void startVoiceRecognition({ fresh: true })
    } else {
      voiceMicPausedByUser.value = true
    }
  }
  if (typeof window !== 'undefined') {
    ;(window as Window & { __wbOpenSixDimTest?: () => void }).__wbOpenSixDimTest = openSixDimTestPreview
    try {
      if (new URLSearchParams(window.location.search).get('wb_test_sixdim') === '1') {
        openSixDimTestPreview()
      }
    } catch {
      /* ignore */
    }
  }
  document.addEventListener('mousedown', onScenePanelOutside)
  document.addEventListener('keydown', onScenePanelKeydown)
  window.addEventListener('resize', onScenePanelReposition)
  window.addEventListener('scroll', onScenePanelReposition, true)
})
watch(tierPanelOpen, (open) => {
  if (open) nextTick(() => updateTierPanelAnchor())
})
watch(empPanelOpen, (open) => {
  if (open) nextTick(() => updateEmpPanelAnchor())
})
watch(
  () => wbSidebar.mobileOpen,
  (open) => {
    if (open) {
      tierPanelOpen.value = false
      empPanelOpen.value = false
    }
  },
)
watch(
  () => wbSidebar.activeMode,
  (mode, prev) => {
    if (mode === 'direct') {
      voiceCasualChatMode.value = false
      platformChatMode.value = false
    } else {
      applySidebarModeSideEffects(mode)
    }
    if (mode === 'voice') {
      wbSidebar.closeMobile()
      ensureVoiceEmployeeIntent()
      void unlockVoiceAudioPlayback()
      streamingTts.warmUp()
      if (!voiceListening.value) {
        if (wbNav.isMobile) {
          voiceMicPausedByUser.value = true
          voiceError.value = ''
        } else if (!voiceMicPausedByUser.value) {
          void startVoiceRecognition({ fresh: true })
        }
      }
    } else if (prev === 'voice') {
      voiceChat.clearContinuousSilenceTimer()
      voiceChat.stopSilenceWatchdog()
      if (voiceListening.value || voiceState.value === 'listening') {
        void stopVoiceRecognition()
      }
      if (streamingTts.state.value !== 'idle') {
        streamingTts.stop()
      }
      voiceState.value = 'idle'
    }
  },
)
/** cascade 播报时暂停 ASR；unified/s2s 保持麦克风全双工，靠 barge-in */
watch(
  () => streamingTts.state.value,
  (state, prev) => {
    if (wbSidebar.activeMode !== 'voice' || voiceMicPausedByUser.value) return
    if (voiceUsePhonePipeline.value) return
    if (state !== 'idle' && prev === 'idle' && voiceListening.value) {
      void voiceChat.stopListening()
    }
  },
)
onDeactivated(() => {
  window.removeEventListener('wb-mode-switch', handleModeSwitchFromSidebar)
  dismissHomeBodyOverlays()
})
watch(
  () => route.name,
  (name) => {
    const n = String(name || '')
    if (n !== 'workbench-home' && n !== 'home') {
      dismissHomeBodyOverlays()
    }
  },
)
watch(
  [planSession, pendingHandoff, orchPhase, finalizeLoading],
  () => {
    syncVoiceWorkPhase()
  },
  { deep: true },
)
watch(directChatEmployeeId, (v) => {
  try {
    const s = String(v || '').trim()
    if (s) sessionStorage.setItem(WB_DIRECT_CHAT_EMPLOYEE_ID_KEY, s)
    else sessionStorage.removeItem(WB_DIRECT_CHAT_EMPLOYEE_ID_KEY)
  } catch {
    /* ignore */
  }
})
watch(directWebSearchEnabled, (enabled) => {
  try {
    sessionStorage.setItem(WB_DIRECT_WEB_SEARCH_KEY, JSON.stringify({ enabled: Boolean(enabled) }))
  } catch {
    /* ignore */
  }
})
watch(
  [directImageGenEnabled, directImageSize, directImageStyle, directImageCount],
  () => {
    try {
      sessionStorage.setItem(
        WB_DIRECT_IMAGE_GEN_KEY,
        JSON.stringify({
          enabled: directImageGenEnabled.value,
          size: directImageSize.value,
          style: directImageStyle.value,
          count: directImageCount.value,
        }),
      )
    } catch {
      /* ignore */
    }
  },
)
watch(
  [directVideoGenEnabled, directVideoAspect, directVideoDurationSec],
  () => {
    try {
      sessionStorage.setItem(
        WB_DIRECT_VIDEO_GEN_KEY,
        JSON.stringify({
          enabled: directVideoGenEnabled.value,
          aspect: directVideoAspect.value,
          durationSec: directVideoDurationSec.value,
        }),
      )
    } catch {
      /* ignore */
    }
  },
)
watch(
  () => Boolean(planSession.value?.loading),
  (loading) => {
    if (__wbState.planLoadingIntervalId !== null) {
      clearInterval(__wbState.planLoadingIntervalId)
      __wbState.planLoadingIntervalId = null
    }
    planLoadingAdvance.value = 0
    if (!loading) return
    const step = () => {
      const ps = planSession.value
      const list = ps?.phase === 'summary' ? planLoadingStepsSummary : planLoadingStepsChat
      const max = Math.max(0, list.length - 1)
      if (planLoadingAdvance.value < max) planLoadingAdvance.value += 1
    }
    __wbState.planLoadingIntervalId = window.setInterval(step, 2000)
  },
)
watch(
  [
    planSession,
    planReplyDraft,
    planOptionSelections,
    pendingHandoff,
    workflowLinkOffer,
    finalizeLoading,
    finalizeError,
    orchestrationSession,
    orchestrationSessionId,
    orchPhase,
    orchestrationEtaSeconds,
    orchestrationEtaReason,
    orchTimingStartMs,
    composerIntent,
    draft,
    modFrontendEnabled,
    activeGear,
  ],
  cacheMakeProgress,
  { deep: true },
)
watch(
  () => ({ ...planOptionOtherText }),
  cacheMakeProgress,
  { deep: true },
)
onBeforeUnmount(() => {
  butlerTrayStore.clearActions()
  document.removeEventListener('mousedown', onScenePanelOutside)
  document.removeEventListener('keydown', onScenePanelKeydown)
  window.removeEventListener('resize', onScenePanelReposition)
  window.removeEventListener('scroll', onScenePanelReposition, true)
  pollStop.value = true
  stopOrchestrationElapsedTicker()
  closePlanDiagramPreview()
  if (__wbState.planLoadingIntervalId !== null) {
    clearInterval(__wbState.planLoadingIntervalId)
    __wbState.planLoadingIntervalId = null
  }
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', onLlmDocPointerDown, true)
  window.removeEventListener('keydown', onLlmEscape)
  window.removeEventListener('wb-mode-switch', handleModeSwitchFromSidebar)
  window.removeEventListener('wb-open-settings', onWbOpenSettings)
  window.removeEventListener('wb-new-chat', onWbNewChat)
  window.removeEventListener('wb-pick-conversation', onWbPickConversation)
  stopDirectVoice()
  stopMakeVoice()
  stopDirectTtsPlayback()
  voiceS2s.disconnect()
})
const voiceKickerText = computed(() => voiceState.value === 'idle' ? '' : voiceStatusText.value)
const _voiceKickerTw = useTypewriter(voiceKickerText, 40, activeModeReset)
watch(
  () => {
    const ps = planSession.value
    if (!ps?.messages?.length) return ''
    for (let i = ps.messages.length - 1; i >= 0; i--) {
      if (ps.messages[i].role === 'assistant') return ps.messages[i].content
    }
    return ''
  },
  () => {
    planOptionSelections.value = {}
    clearPlanOptionOtherText()
  },
)

  return {
    ...ctx, onDirectVoicePointerDown, onDirectVoiceClick, startDirectVoice, toggleDirectVoice,
    startMakeVoice, toggleMakeVoice, onWbNewChat, applySidebarModeSideEffects, handleModeSwitchFromSidebar,
    applyWbGearFromRoute, voiceKickerText, _voiceKickerTw,
  }
}

export type useWbHandleModeSwitchFromSidebarBinds = ReturnType<typeof useWbHandleModeSwitchFromSidebar>
