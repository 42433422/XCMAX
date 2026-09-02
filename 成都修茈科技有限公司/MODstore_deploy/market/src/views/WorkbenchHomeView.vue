<template>
  <div class="wb-home">
    <WbSceneHeader :wb="wb" />
    <main class="wb-main-area">
      <div class="wb-mode-content">
        <section
          v-if="wbSidebar.activeMode !== 'voice'"
          class="wb-mode-scene"
          :class="{
            'wb-mode-scene--direct-flow': showDirectStyleConversation && directMessages.length,
            'wb-mode-scene--direct-empty': showDirectStyleConversation && !directMessages.length,
            'wb-mode-scene--make-platform': showMakePlatformCasualChat,
            'wb-mode-scene--make-flow': wbSidebar.activeMode === 'make' && !platformChatMode && makeHasActiveTask,
          }"
          :style="directFontPxStyle"
        >
          <WbSceneTeleports :wb="wb" />
          <template v-if="showDirectStyleConversation">
              <WbDirectEmpty :wb="wb" />
              <WbDirectShell :wb="wb" />

              <WbDirectModals :wb="wb" />
          </template>

        <template v-if="wbSidebar.activeMode === 'make' && !wbNav.isMobile && !platformChatMode">
          <WbPlanPanel :wb="wb" />

      <WbPlanPanels :wb="wb" />

      <WbPlanComposer :wb="wb" />
        </template>
        </section>

            <WbVoiceScene :wb="wb" />
      </div>
    </main>

    <WbRootTeleports :wb="wb" />
  </div>
</template>

<script setup lang="ts">
import './workbench-home-v7.css'
import './workbench-home-ux.css'
import type { Ref } from 'vue'
import { assembleWorkbenchHome } from './workbench-home/assemble'
import WbSceneHeader from './workbench-home/WbSceneHeader.vue'
import WbSceneTeleports from './workbench-home/WbSceneTeleports.vue'
import WbDirectEmpty from './workbench-home/WbDirectEmpty.vue'
import WbDirectShell from './workbench-home/WbDirectShell.vue'
import WbDirectModals from './workbench-home/WbDirectModals.vue'
import WbPlanPanel from './workbench-home/WbPlanPanel.vue'
import WbPlanPanels from './workbench-home/WbPlanPanels.vue'
import WbPlanComposer from './workbench-home/WbPlanComposer.vue'
import WbVoiceScene from './workbench-home/WbVoiceScene.vue'
import WbRootTeleports from './workbench-home/WbRootTeleports.vue'

const wb = assembleWorkbenchHome()

const {
  suggestModIdFromText, LLM_CATEGORY_ORDER, router, route, wbSidebar, wbNav, draft, displayName,
  workbenchErrorMessage, workbenchHttpStatus, inputRef, handoffPanelRef, pendingHandoff, makeCompletionResult, employeeSixDimModalOpen, employeeSixDimReport,
  makeCompletionRef, finalizeLoading, finalizeError, orchestrationSession, orchestrationSessionId, pollStop, orchPhase, orchestrationEtaSeconds,
  orchestrationEtaReason, __wbState, orchTimingStartMs, orchElapsedTick, workflowLinkOffer, linkMods, linkModId, linkBusy,
  linkError, planSession, planReplyDraft, autoPilotRunning, autoPilotError, voiceChecklistPaused, planOptionSelections, PLAN_OPTION_OTHER_ID,
  planOptionOtherText, clearPlanOptionOtherText, planPanelRef, planSurfaceKey, MAKE_PROGRESS_CACHE_KEY, MAKE_PROGRESS_CACHE_TTL_MS, planLoadingStepsSummary, planLoadingStepsChat,
  planLoadingAdvance, planLoadingStepLabelsForUi, planLoadingProgressPercent, knowledgeStatus, knowledgeDocs, knowledgeLoading, knowledgeUploading, knowledgeError,
  knowledgeFileInputRef, knowledgeDragActive, isEmbeddingConfigured, CANVAS_SKILL_INTENT, isCanvasSkillIntent, composerIntent, modFrontendEnabled, activeGear,
  showDirectChatSurface, showMakePlatformCasualChat, showDirectStyleConversation, platformChatMode, voiceCasualChatMode, voiceHumanChatMode, voiceSessionModeForIntent, persistPlatformChatMode,
  directDraft, directPlaceholder, directFileInputRef, directAttachedFiles, directGeneratedFiles, officeReadCacheByConversation, directGeneratingFile, directGeneratingFormatLabel,
  showDirectHomeFileStrip, directLoading, directSendPending, directError, directVoiceListening, directVoiceAudioLevel, directWaveformCanvas, ttsAutoRead,
  currentThemeIsLight, isLightTheme, toggleTheme, makeVoiceListening, directVoiceRecognizing, makeVoiceRecognizing, directVoicePermissionHint, makeVoicePermissionHint,
  WB_DIRECT_CHAT_EMPLOYEE_ID_KEY, WB_DIRECT_WEB_SEARCH_KEY, WB_DIRECT_IMAGE_GEN_KEY, WB_DIRECT_VIDEO_GEN_KEY, directChatEmployeeId, directEmployeeOptions, directWebSearchEnabled, directWebSearching,
  directImageGenEnabled, directVideoGenEnabled, directMediaGenerating, directImageSize, directImageStyle, directImageCount, directVideoAspect, directVideoDurationSec,
  conversations, activeConversationId, activeConversation, directMessages, directIsDragging, editingMessageId, editingDraft, personalSettings,
  personalSettingsOpen, streamingTts, voiceS2s, voiceUnified, unifiedAsrBridge, voiceUseUnified, voiceUseS2S, voiceUsePhonePipeline,
  onPersonalSettingsUpdate, showAgentMarket, showVoicePhone, showMediaGen, mediaGenInitialTab, allBots, activeBotId, activeBot,
  _directTaskLine, speakingMessageId, stopDirectTtsPlayback, directCanSend, directSendDisabled, butlerTrayStore, butlerDownloadHistory, agentStore,
  headerGeneratedStripPlan, composerAttachmentStripPlan, headerFileStripPlan, directVisibleAttachedFiles, directComposerVisibleFiles, butlerFileOverflowCount, directHiddenAttachmentCount, directComposerHiddenCount,
  openButlerFileTray, directAttachmentMentions, CONSUMPTION_TIER_STORAGE_KEY, readStoredConsumptionTier, consumptionTier, tierPanelOpen, empPanelOpen, empDropdownOpen,
  tierTriggerRef, empTriggerRef, tierPanelAnchorStyle, empPanelAnchorStyle, homeStarterCards, homeSuggestionChips, recentHomeConversations, updateTierPanelAnchor,
  updateEmpPanelAnchor, toggleTierPanel, toggleDirectWebSearch, directAttachHint, toggleDirectImageGen, toggleDirectVideoGen, toggleEmpPanel, applyStarterPrompt,
  onScenePanelOutside, onScenePanelKeydown, onScenePanelReposition, titleEnterDone, composerPanelEnter, contentEnter, directBoxEnter, useTypewriter,
  directAttachExpanded, convPopoverOpen, voiceMessages, voiceSessionState, voiceError, voiceMicFallbackHint, voiceState, voiceReport,
  waveformCanvas, voiceWorkbench, voiceChatPhase, voiceWorkPhase, voiceChatBusy, voiceInjectQueue, syncWorkPhase, pushInject,
  clearInjectQueue, VOICE_TTS_FEED_OPTS, voiceAutoSend, WAVE_BAR_COUNT, waveBarHeights, directWaveBarHeights, drawDirectWaveform, voiceProgress,
  inlineAsr, directVoicePhase, makeVoicePhase, directVoiceBtnClass, makeVoiceBtnClass, directVoiceAria, makeVoiceAria, directVoiceStatusText,
  makeVoiceStatusText, directVoiceCanCancel, makeVoiceCanCancel, canSpeculateForPartial, appendVoiceUserTurn, phoneTurnTextDelta, cancelSpeculativeVoiceTurn, triggerVoiceBargeIn,
  voiceAssistantSpeaking, voiceHasAssistantContent, voiceTitle, directFileChipTitle, formatEmbeddingLabel, directAttachmentKind, directAttachmentKindLabel, directAttachmentStatusText,
  directAttachmentNote, resolveDirectFileEmployeeId, applyDirectReadEmployeePick, openDirectFilePicker, makeDirectAttachId, retrieveWebForDirect, buildDirectAttachItem, appendAttachmentMentions,
  prepareDirectVisionFile, userFacingOutputDownloads, pushDirectGeneratedDownloads, cacheOfficeReadResults, getCachedOfficeReadResults, beginDirectGenerating, clearDirectGenerating, runDirectOfficeGeneratePhase,
  removeDirectGeneratedFile, downloadGeneratedOutput, removeDirectAttachedFile, persistConversations, ensureActiveConversation, patchActiveConversation, appendUserAndAssistant, updateAssistantMessage,
  buildHumanChatStylePrompt, buildSystemPrompt, _rebuildContextMessages, directEmployeeSystemHint, withRequestTimeout, formatDirectChatError, handleDirectChatAuthFailure, DIRECT_KB_RETRIEVE_MS,
  DIRECT_WEB_SEARCH_MS, markDirectFirstToken, runDirectEmployeeReadForLlm, stopGeneration, downloadOutput, pickHomeConversation, formatHomeConvTime, startEditUserMessage,
  cancelEditUserMessage, setMessageFeedback, speakMessage, copyConversationLink, setActiveConversation, pickConversation, convTimeFormat, isFileEmployeePurposeToggle,
  isFileAutoReadEmployee, _pinConversation, _renameConversation, _exportConversation, _removeConversation, _clearAllConversations, directDragDepth, dragHasFiles,
  onSurfaceDragEnter, onSurfaceDragOver, onSurfaceDragLeave, refreshAllBots, onCreateAgent, onRemoveAgent, onFavoriteAgent, onStartWithAgent,
  clearActiveBot, customerServiceQueryContext, stripCustomerServiceEntryQueryFromUrl, applyCustomerServiceRouteContext, directFontPxStyle, videoSizeForAspect, insertGeneratedToChat, onComposerFocus,
  buildVoiceTopicHint, ensureVoiceEmployeeIntent, shouldRouteVoiceAsEmployee, shouldAutoDismissStaleVoicePlan, ensureEmployeePlanContextFromVoice, textsSimilarForFinalize, _speakText, syncVoiceWorkPhase,
  requireLoginForWorkbenchUse, llmCatalog, llmCatalogLoading, llmCatalogError, selectedProvider, selectedModel, modelMode, llmDdOpen,
  llmMobileSheetOpen, _canvasSkillMeta, INTENT_META, intentMeta, intentGuideCollapsed, catalogEmployeeRows, catalogModRows, pickEmployeeKey,
  pickModId, _catalogEmployeesForPick, _catalogModsForPick, _pickedEmployeeRow, pickedModRow, _pickedModManifestVersion, _pickedModManifestName, _pickedModManifestDescription,
  truncateWorkbenchText, _releaseChannelLabel, loadDirectEmployeeOptions, llmMobilePickerSummary, hasModRepo, hasEmployeeIntent, isMakeToolbarIntentActive, buildVoiceRouteContext,
  intentRepoPickShow, showIntentGuide, loadWorkbenchRepoPicks, _goEditEmployeeFromPick, _goEditModFromPick, _composerMainTitle, handoffDescLabel, orchestrationButtonLabel,
  orchestrationButtonPendingLabel, makeHasActiveTask, _makeComposerRows, orchestrationProgress, orchQualityReport, orchQualityMeta, orchVibecodingMeta, formatWallClockSec,
  stopOrchestrationElapsedTicker, startOrchestrationElapsedTicker, ORCH_ESTIMATE_SYSTEM, parseOrchestrationEtaFromLlmText, fallbackOrchestrationSecondsEstimate, orchestrationEtaDisplay, orchestrationTimingTooltip, orchestrationElapsedDisplay,
  canRunOrchestration, handoffFootNote, handoffAssetNote, hasRepo, hasWorkflow, _showDirectTierFab, _hasScriptWorkflowRoute, hasEmployee,
  _hasPlans, gearNavUserUnlocked, _gearNavHardLocked, _unlockGearNav, greetingLine, placeholder, makeComposerInput, _makeComposerInputLabel,
  makeComposerPlaceholder, composerSendDisabled, currentLlmBlock, currentProviderLabel, modelModeHint, modelPickerEnabled, categoryLabel, modelsForWorkbenchCategory,
  syncManualSelectionFromPreferences, loadLlmCatalogForWorkbench, onWorkbenchProviderChange, toggleLlmDd, pickProvider, pickModel, onLlmDocPointerDown, onLlmEscape,
  _orchStepClass, _handoffRunStatusLine, orchStepRunningSec, _stepLastMsgChange, orchStepSlowHint, _trackStepMessages, structuredStepMessage, stepMsgSummary,
  stepMsgCurrentTool, stepMsgTodos, stepMsgSlowHint, cachedFileMetadata, normalizePlanMessages, serializablePlanSession, restorePlanSession, serializablePendingHandoff,
  restorePendingHandoff, makeHasCachedProgress, cacheMakeProgress, clearMakeProgressCache, restoreMakeProgressCache, applyInlineVoiceText, stopInlineVoiceCapture, clearInlineVoicePermissionHint,
  setInlineVoicePermissionHint, cancelInlineVoice, stopInlineVoice, onInlineHoldMove, onDirectVoicePointerMove, stopDirectVoice, voiceBtnLongPressStart, voiceBtnLongPressCancel,
  stopMakeVoice, onWbOpenSettings, onWbPickConversation, clearWorkbenchHandoffSession, isModHostStackSurveyQuestion, normalizePlanOptions, parsePlanAssistantContent, planQuickOptions,
  planPanelTitle, mermaidChecklistLabel, dismissPlanSessionFromVoice, dismissStaleVoicePlanSilently, planChecklistFlowMarkdown, buildChecklistFlowMarkdown, cancelPlanSummary, compactPlanVisibleText,
  extractInitialIdeaFromHandoff, MAKE_HERO_TITLE_MAX, makeHeroTitle, activeModeReset, directTitleText, directSubText, makeKickerText, makeTitleText,
  directTitleTw, directSubTw, makeKickerTw, makeTitleTw, voiceTitleText, _voiceTitleTw, buildPlanSummarySystemPrompt, parsePlanSummary,
  canSendPlanQuickPicks, planAssistantParts, planDiagramError, planDiagramPreviewIdx, planDiagramPreviewMountRef, planDiagramPreviewViewportRef, planPreviewScale, planPreviewTx,
  planPreviewTy, planDiagramPreviewPanStyle, clearPlanDiagramPreviewPointerListeners, onPlanDiagramPreviewWheel, onPlanDiagramPreviewPointerDown, planDiagramPreviewZoomStep, planDiagramPreviewFitView, openPlanDiagramPreview,
  closePlanDiagramPreview, getMermaidSingleton, flushPlanMermaidDiagrams, dismissPlanSession, loadKnowledgeDocuments, openKnowledgeFilePicker, onKnowledgeDragEnter, onKnowledgeDragLeave,
  fileExtension, fileKind, fileKindClass, fileKindLabel, formatBytes, deleteKnowledgeDocument, formatKnowledgeContext, clearMakePanelsForCasualChat,
  retrieveKnowledgeForDirect, retryOrchStep, resetMakeComposer, dismissWorkflowLinkOffer, loadLinkMods, openWorkflowCanvasOnly, confirmWorkflowModLink, dismissPendingHandoff,
  buildMakeCompletionResult, scrollMakeFlowToEnd, openMakeCompletionPrimary, openMakeCompletionSecondary, closeEmployeeSixDimModal, dismissHomeBodyOverlays, openSixDimTestPreview, tryOpenEmployeeSixDimModal,
  persistManualLlmIfNeeded, pollWorkbenchSession, resumeCachedOrchestration, handlePhonePartialStable, loadUsableMediaCatalog, buildVoiceWorkbenchPrompt, _confirmVoiceAndOpenHandoff, _applyStarter,
  buildPlanSystemPrompt, buildChecklistGenerationSystemPrompt, formatPlanMessagesForBrief, enrichEmployeeHandoffBeforeOrchestration, friendlyPlanPanelApiError, _checklistBodyToResult, parseChecklistNumberedTail, parseChecklistBlock,
  _providerRowHasUsableKey, RESOLVE_CHAT_CACHE_MS, pickVisionModelFromBlock, pickUsableVisionProviderModel, resolveChatProviderModel, uploadDirectAttachedFile, onDirectFilesChange, runDirectChatTurn,
  regenerateAssistant, commitEditedUserMessage, setFilePurpose, onComposerPaste, onSurfaceDrop, ingestComposerFiles, mediaGenRunner, sendDirectChat,
  handleVoicePhoneTurn, onDirectKeydown, applyEmployeeSessionClassify, tryOpenEmployeePlanFromExplicitCommand, resolveEmployeeClassification, resummarizeVoiceEmployeePlan, estimateOrchestrationSeconds, uploadKnowledgeFiles,
  onKnowledgeFileChange, onKnowledgeDrop, scrollPlanIntoView, appendUserAndAssistantPlanTurn, summarizePlanSession, openPlanSession, backSummaryToComposer, confirmSummaryAndStartPlanning,
  ensureAutoPilotReadyChatTurns, fastEnterChatForAutoPilot, pickPlanOption, autoPickPlanQuickOptions, submitPlanUserMessage, sendPlanReply, sendPlanReplyFromQuickPicks, backPlanToChat,
  confirmPlanAndOpenHandoff, voiceMicLevelRaw, voiceAsrAdapter, handlePhoneUtteranceFinalize, handleVoiceUtteranceReady, startSpeculativeVoiceTurn, voiceChat, voiceDraft,
  voiceTranscript, voiceLivePreview, voiceListening, voiceAudioLevel, voiceMicPausedByUser, voiceSpeculating, noteVoiceSubmitted, resumeVoiceListeningAfterTurn,
  drainVoiceUtteranceQueue, dispatchVoiceUtterance, executeLegacyVoiceRoute, resumeVoiceAfterChatTurn, dispatchEmployeeVoiceUtterance, dispatchVoiceUtteranceCore, confirmEmployeeChecklistAndRunFromVoice, voiceEmployeePlanPostOpen,
  openPlanSessionFromVoice, resumeVoiceListeningInSayMode, enablePlatformChatMode, disablePlatformChatMode, togglePlatformChatMode, exitMakeToolbarToCasualChat, switchMakeIntent, drawWaveform,
  voiceAsrActiveId, voiceAsrBackendLabel, voiceDockDraft, showVoiceWaveform, voiceAsrConnecting, voiceAsrListening, voiceDockRecognizing, onVoiceDockSend,
  onVoiceMicToggle, resumeVoiceMic, forcePauseVoiceSession, resetVoiceListenSession, resetVoiceCaptureUi, finishContinuousUtterance, activateVoiceContinuous, voiceOrbMode,
  voiceOrbHint, voiceOrbActive, voiceStatusText, isGearAxisLocked, newConversationHandler, resetVoiceSession, onOrbClick, speakTextAndListen,
  _toggleVoiceListening, stopVoiceAsr, _onVoiceAsrError, startVoiceRecognition, stopVoiceRecognition, ensureVoiceListening, interruptVoice, onVoiceDismissPlanPanel,
  handleVoicePlanReplySmart, handleVoicePlanReply, injectVoiceDuringWork, runVoiceUnifiedTurn, runVoiceS2STurn, runVoiceChatTurn, speakVoiceShort, _submitVoiceTurn,
  _speakTextAndContinue, startInlineVoice, onInlineHoldStart, applyMakeCompletion, maybeAutoOpenMakeCompletionInVoiceMode, onDirectVoicePointerDown, onDirectVoiceClick, startDirectVoice,
  toggleDirectVoice, startMakeVoice, toggleMakeVoice, onWbNewChat, applySidebarModeSideEffects, handleModeSwitchFromSidebar, applyWbGearFromRoute, voiceKickerText,
  _voiceKickerTw, finishInlineHoldAndSend, runOrchestration, runAutoPilotFromSummary, runAutoPilotFromChat, requestExecutionChecklist, scheduleVoiceChecklistAutoStart, submitDraft,
  onComposerSendClick, onInlineHoldEnd, onDirectVoicePointerUp, onComposerKeydown,
} = wb

const coverageHooks = {
  __setRef(key: string, value: unknown) {
    if (key === 'planOptionOtherText') {
      Object.assign(planOptionOtherText, value && typeof value === 'object' ? value : {})
      return true
    }
    if (key === 'planDiagramPreviewOpen') {
      planDiagramPreviewIdx.value = value ? 0 : null
      return true
    }
    if (key === 'planDiagramPreviewScale') {
      planPreviewScale.value = Number(value) || 1
      return true
    }
    if (key === 'planDiagramPreviewTranslate' && value && typeof value === 'object') {
      const v = value as { x?: number; y?: number }
      planPreviewTx.value = Number(v.x) || 0
      planPreviewTy.value = Number(v.y) || 0
      return true
    }
    const refs = {
      activeBotId,
      activeConversationId,
      allBots,
      autoPilotError,
      autoPilotRunning,
      composerIntent,
      contentEnter,
      conversations,
      directChatEmployeeId,
      directDraft,
      directEmployeeOptions,
      directGeneratedFiles,
      directGeneratingFile,
      directVoiceAudioLevel,
      directVoiceListening,
      directVoicePermissionHint,
      directVoiceRecognizing,
      directAttachedFiles,
      directError,
      directImageCount,
      directImageGenEnabled,
      directImageSize,
      directImageStyle,
      directLoading,
      directMediaGenerating,
      directSendPending,
      directVideoAspect,
      directVideoDurationSec,
      directVideoGenEnabled,
      directWebSearchEnabled,
      draft,
      empDropdownOpen,
      empPanelOpen,
      finalizeError,
      finalizeLoading,
      knowledgeDocs,
      knowledgeError,
      knowledgeStatus,
      knowledgeUploading,
      linkBusy,
      linkError,
      linkModId,
      linkMods,
      llmCatalog,
      llmDdOpen,
      llmMobileSheetOpen,
      makeCompletionResult,
      makeVoiceListening,
      makeVoicePermissionHint,
      makeVoiceRecognizing,
      modelMode,
      orchPhase,
      orchestrationEtaReason,
      orchestrationEtaSeconds,
      orchestrationSession,
      orchestrationSessionId,
      pendingHandoff,
      personalSettings,
      planDiagramError,
      planDiagramPreviewIdx,
      planDiagramPreviewMountRef,
      planDiagramPreviewViewportRef,
      planOptionSelections,
      planReplyDraft,
      planSession,
      planPreviewScale,
      planPreviewTx,
      planPreviewTy,
      platformChatMode,
      pollStop,
      selectedModel,
      selectedProvider,
      showAgentMarket,
      showMediaGen,
      showVoicePhone,
      tierPanelOpen,
      titleEnterDone,
      ttsAutoRead,
      voiceAudioLevel,
      voiceCasualChatMode,
      voiceError,
      voiceMessages,
      voiceMicFallbackHint,
      voiceReport,
      voiceState,
      waveformCanvas,
      workflowLinkOffer,
    } as Record<string, Ref<unknown>>
    const target = refs[key]
    if (!target) return false
    target.value = value
    return true
  },
  appendVoiceUserTurn,
  applyDirectReadEmployeePick,
  closePlanDiagramPreview,
  buildDirectAttachItem,
  canSpeculateForPartial,
  clearPlanOptionOtherText,
  clearPlanDiagramPreviewPointerListeners,
  confirmSummaryAndStartPlanning,
  customerServiceQueryContext,
  directAttachmentKind,
  directAttachmentKindLabel,
  directAttachmentNote,
  directAttachmentStatusText,
  directFileChipTitle,
  drawDirectWaveform,
  drawWaveform,
  formatBytes,
  formatDirectChatError,
  formatEmbeddingLabel,
  formatKnowledgeContext,
  isCanvasSkillIntent,
  isEmbeddingConfigured,
  onPlanDiagramPreviewPointerDown,
  onPlanDiagramPreviewWheel,
  openPlanDiagramPreview,
  parsePlanSummary,
  persistManualLlmIfNeeded,
  planDiagramPreviewFitView,
  planDiagramPreviewZoomStep,
  pollWorkbenchSession,
  readStoredConsumptionTier,
  requestExecutionChecklist,
  resolveDirectFileEmployeeId,
  resolveChatProviderModel,
  retryOrchStep,
  runAutoPilotFromChat,
  runAutoPilotFromSummary,
  runOrchestration,
  applyCustomerServiceRouteContext,
  applyMakeCompletion,
  applyStarterPrompt,
  applyWbGearFromRoute,
  autoPickPlanQuickOptions,
  backPlanToChat,
  backSummaryToComposer,
  cancelEditUserMessage,
  closeEmployeeSixDimModal,
  commitEditedUserMessage,
  confirmPlanAndOpenHandoff,
  confirmWorkflowModLink,
  deleteKnowledgeDocument,
  dismissHomeBodyOverlays,
  dispatchVoiceUtterance,
  downloadGeneratedOutput,
  ensureVoiceListening,
  fileExtension,
  fileKind,
  fileKindClass,
  fileKindLabel,
  handleDirectChatAuthFailure,
  handleVoicePlanReplySmart,
  handleVoiceUtteranceReady,
  loadDirectEmployeeOptions,
  loadLinkMods,
  markDirectFirstToken,
  onComposerKeydown,
  onComposerPaste,
  onKnowledgeDragEnter,
  onKnowledgeDragLeave,
  onKnowledgeDrop,
  onKnowledgeFileChange,
  onRemoveAgent,
  onStartWithAgent,
  openEmployeeSixDimModal: tryOpenEmployeeSixDimModal,
  openKnowledgeFilePicker,
  openMakeCompletionPrimary,
  openMakeCompletionSecondary,
  openSixDimTestPreview,
  openWorkflowCanvasOnly,
  pickPlanOption,
  pushDirectGeneratedDownloads,
  regenerateAssistant,
  removeDirectAttachedFile,
  removeDirectGeneratedFile,
  resetMakeComposer,
  retrieveKnowledgeForDirect,
  retrieveWebForDirect,
  runDirectChatTurn,
  runDirectEmployeeReadForLlm,
  runDirectOfficeGeneratePhase,
  runVoiceChatTurn,
  runVoiceS2STurn,
  sendDirectChat,
  sendPlanReplyFromQuickPicks,
  setFilePurpose,
  speakTextAndListen,
  startEditUserMessage,
  startInlineVoice,
  startSpeculativeVoiceTurn,
  stopGeneration,
  submitDraft,
  switchMakeIntent,
  toggleDirectImageGen,
  toggleDirectVideoGen,
  toggleDirectWebSearch,
  toggleEmpPanel,
  togglePlatformChatMode,
  toggleTierPanel,
  triggerVoiceBargeIn,
  tryOpenEmployeeSixDimModal,
  uploadDirectAttachedFile,
  uploadKnowledgeFiles,
  suggestModIdFromText,
  voiceAsrAdapter,
  voiceAsrBackendLabel,
  voiceSessionModeForIntent,
}
defineExpose({
  isGearAxisLocked,
  __coverage: coverageHooks,
})
if (import.meta.env.MODE === 'test') {
  const testGlobal = globalThis as typeof globalThis & {
    __WORKBENCH_HOME_COVERAGE_HOOKS__?: typeof coverageHooks
  }
  testGlobal.__WORKBENCH_HOME_COVERAGE_HOOKS__ = coverageHooks
}
</script>

<style src="./workbench-home/workbench-home.css"></style>
