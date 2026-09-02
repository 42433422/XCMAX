<script setup lang="ts">
import SiriOrb from '../../components/workbench/SiriOrb.vue'
import VoiceTaskPanels from '../../components/workbench/voice/VoiceTaskPanels.vue'
import VoiceFlowPanel from '../../components/workbench/voice/VoiceFlowPanel.vue'
import VoiceDock from '../../components/workbench/voice/VoiceDock.vue'
import type { WorkbenchHomeCtx } from './assemble'

// 拆分自 WorkbenchHomeView.vue 模板（原第 1678–1774 行）；模板逐字迁移，行为不变。
const props = defineProps<{ wb: WorkbenchHomeCtx }>()

const {
  wbSidebar, wbNav, draft, pendingHandoff, makeCompletionResult, finalizeLoading,
  finalizeError, orchestrationSession, orchPhase, planSession, platformChatMode, streamingTts,
  voiceMessages, voiceError, voiceMicFallbackHint, voiceState, voiceReport, waveformCanvas,
  voiceWorkPhase, voiceChatPhase, voiceChatBusy, voiceInjectQueue, voiceMicLevelRaw, voiceProgress,
  voiceAsrAdapter, voiceAsrBackendLabel, voiceListening, voiceAudioLevel, voiceLivePreview, voiceMicPausedByUser,
  voiceTranscript, voiceSpeculating, voiceDockDraft, voiceAssistantSpeaking, showVoiceWaveform, voiceAsrConnecting,
  voiceAsrListening, voiceDockRecognizing, voiceHasAssistantContent, onVoiceDockSend, onVoiceMicToggle, voiceOrbMode,
  voiceOrbHint, voiceOrbActive, voiceTitle, voiceStatusText, onOrbClick, onVoiceDismissPlanPanel,
  orchestrationProgress, canRunOrchestration, dismissPendingHandoff, openMakeCompletionPrimary, runOrchestration,
} = props.wb
</script>

<template>
            <section
              v-if="wbSidebar.activeMode === 'voice'"
              class="wb-mode-scene wb-voice-scene wb-voice-scene--no-contain"
              :class="{
                'wb-voice-scene--chatting': voiceMessages.length > 0 || voiceListening || voiceChatBusy,
                'wb-voice-scene--mobile': wbNav.isMobile,
              }"
            >
  <div
    v-show="!wbNav.isMobile || !voiceMessages.length"
    class="wb-voice-orb-area"
    :class="{ 'wb-voice-orb-area--active': voiceOrbActive && !wbNav.isMobile }"
  >
    <button
      type="button"
      class="wb-voice-orb-btn"
      :aria-label="voiceOrbHint || voiceTitle"
      @click="onOrbClick"
    >
      <SiriOrb
        :mode="voiceOrbMode"
        :progress="voiceProgress"
        :audio-level="voiceAudioLevel"
      />
    </button>
    <p v-if="voiceOrbHint" class="wb-voice-orb-hint">{{ voiceOrbHint }}</p>
    <p v-else-if="!voiceMessages.length" class="wb-voice-orb-status">{{ voiceStatusText }}</p>
  </div>
  <VoiceTaskPanels
    v-if="!platformChatMode"
    :plan-session="planSession"
    :pending-handoff="pendingHandoff"
    :orchestration-session="orchestrationSession"
    :orch-phase="orchPhase"
    :voice-inject-queue="voiceInjectQueue"
    :can-run-orch="canRunOrchestration"
    :orchestration-progress="orchestrationProgress"
    :finalize-loading="finalizeLoading"
    :finalize-error="finalizeError"
    :make-completion-result="makeCompletionResult"
    @confirm-generate="() => void runOrchestration()"
    @dismiss-handoff="dismissPendingHandoff"
    @dismiss-plan="() => void onVoiceDismissPlanPanel()"
    @open-completion="() => void openMakeCompletionPrimary()"
  />
  <div class="wb-voice-flow-host">
    <VoiceFlowPanel
      :messages="voiceMessages"
      :streaming="voiceChatPhase === 'streaming'"
      :live-text="voiceReport"
      :is-live-narrating="voiceAssistantSpeaking"
      :live-user-text="voiceMicPausedByUser ? '' : (voiceTranscript || voiceLivePreview)"
      :mic-paused="voiceMicPausedByUser"
      :recognizing="voiceListening && !voiceMicPausedByUser && Boolean(voiceTranscript || voiceLivePreview)"
      :speculating="voiceSpeculating"
    />
  </div>
  <Teleport to="body">
    <div
      v-if="wbSidebar.activeMode === 'voice'"
      class="wb-voice-bottom wb-voice-bottom--portal"
      :class="{ 'wb-voice-bottom--mobile': wbNav.isMobile }"
    >
      <div class="wb-voice-waveform-wrap" v-if="showVoiceWaveform" ref="waveformWrap">
        <canvas ref="waveformCanvas" class="wb-voice-waveform-canvas" width="720" height="28"></canvas>
      </div>
      <VoiceDock
        :mic-paused="voiceMicPausedByUser"
        :connecting="voiceAsrConnecting"
        :connecting-hint="voiceAsrAdapter.loadingHint.value"
        :recognizing="voiceDockRecognizing"
        :listening="voiceAsrListening"
        :mic-live="voiceMicLevelRaw() >= 0.004"
        :chat-busy="voiceChatBusy"
        :speculating="voiceSpeculating"
        :has-assistant-content="voiceHasAssistantContent"
        :voice-state="voiceState"
        :tts-active="streamingTts.state.value !== 'idle'"
        :work-phase="voiceWorkPhase"
        :asr-backend-label="voiceAsrBackendLabel"
        v-model:draft="voiceDockDraft"
        @toggle-mic="onVoiceMicToggle"
        @send="() => void onVoiceDockSend()"
      />
    </div>
  </Teleport>
  <p v-if="voiceError" class="wb-voice-error" role="alert">{{ voiceError }}</p>
  <p v-else-if="voiceMicFallbackHint" class="wb-voice-soft-hint" role="status">
    {{ voiceMicFallbackHint }}
  </p>
  <p
    v-else-if="voiceAsrAdapter.loadingHint.value && voiceListening && !voiceMicPausedByUser"
    class="wb-voice-loading-hint"
  >
    {{ voiceAsrAdapter.loadingHint.value }}
  </p>
</section>
</template>
