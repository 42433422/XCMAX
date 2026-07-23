<template>
  <Teleport to="body">
    <div
      class="butler-float-root butler-float-root--corp"
      :class="{
        'butler-float-root--contact-page': isContactPage,
        'butler-float-root--speaking': introSpeaking,
      }"
    >
      <AgentPermissionDialog
        v-if="showPermissionDialog"
        corp-mode
        @agree="onConsentAgreed"
        @dismiss="agentStore.dismissLater()"
      />

      <FloatingAgentBall :is-speaking="introSpeaking" force-light corp-mode />
      <Transition name="panel-pop">
        <FloatingAgentPanel
          v-if="isOpen"
          corp-mode
          :handle-input="handleInput"
          :run-intake-task="runIntakeTask"
          @proactive-intro-change="onProactiveIntroChange"
        />
      </Transition>

      <CorpContactIntakeModal v-if="showMobileContactIntake" />
      <!-- 中文字幕仅官网小C；软件工作台/桌面不挂 -->
      <TtsSubtitleOverlay />
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useAgentStore } from '../stores/agent'
import { saveCorpBallPosition } from './corpBallPosition'
import { isCorpMobileViewport } from './corpViewport'
import { useCorpAgentEngine } from '../composables/agent/useCorpAgentEngine'
import { isContactPagePath } from '../content/siteKnowledge'
import type { QuickAction } from '../content/siteKnowledge'
import {
  buildCorpPageIntroScript,
  hasIntroducedPageThisSession,
  isCorpProactiveIntroEnabled,
  markPageIntroduced,
  prefersReducedMotion,
  speakCorpIntro,
  stopCorpIntroSpeech,
} from './corpPageIntro'
import AgentPermissionDialog from '../components/floating-agent/AgentPermissionDialog.vue'
import FloatingAgentBall from '../components/floating-agent/FloatingAgentBall.vue'
import FloatingAgentPanel from '../components/floating-agent/FloatingAgentPanel.vue'
import CorpContactIntakeModal from '../components/floating-agent/CorpContactIntakeModal.vue'
import TtsSubtitleOverlay from '../components/TtsSubtitleOverlay.vue'

const agentStore = useAgentStore()
const { isOpen, showPermissionDialog, position } = storeToRefs(agentStore)
const { handleInput: engineHandleInput, runIntakeTask: engineRunIntakeTask } = useCorpAgentEngine()
const pendingIntakeAction = ref<QuickAction | null>(null)
const introSpeaking = ref(false)
let introTimer: number | null = null
let introSeq = 0

function clipForSpeech(text: string, max = 480): string {
  const t = String(text || '')
    .replace(/\s+/g, ' ')
    .trim()
  if (t.length <= max) return t
  return `${t.slice(0, Math.max(0, max - 1))}…`
}

async function speakAssistantReply(): Promise<void> {
  if (typeof window === 'undefined') return
  if (prefersReducedMotion()) return
  const last = agentStore.messages[agentStore.messages.length - 1]
  if (!last || last.role !== 'assistant' || last.isLoading) return
  const text = clipForSpeech(last.content || '')
  if (!text || text === '…') return

  stopCorpIntroSpeech()
  const seq = ++introSeq
  introSpeaking.value = true
  agentStore.setMode('speaking')
  try {
    await speakCorpIntro(text)
  } finally {
    if (seq === introSeq) {
      introSpeaking.value = false
      if (agentStore.mode === 'speaking') agentStore.setMode('idle')
    }
  }
}

async function handleInput(
  text: string,
  opts?: { skipUserInsert?: boolean; withScreenshot?: boolean; imageDataUrl?: string | null },
): Promise<void> {
  stopCorpIntroSpeech()
  introSpeaking.value = false
  await engineHandleInput(text, opts)
  await speakAssistantReply()
}

async function runIntakeTask(action: QuickAction): Promise<void> {
  stopCorpIntroSpeech()
  introSpeaking.value = false
  await engineRunIntakeTask(action)
  await speakAssistantReply()
}

function flushPendingIntakeFill() {
  const action = pendingIntakeAction.value
  if (!action) return
  pendingIntakeAction.value = null
  agentStore.openPanel()
  void runIntakeTask(action)
}

async function runProactivePageIntro(reason: 'consent' | 'page') {
  if (typeof window === 'undefined') return
  if (!agentStore.consentGiven) return
  if (!isCorpProactiveIntroEnabled()) return

  const pathname = window.location.pathname || '/'
  const { pageId, text } = buildCorpPageIntroScript(pathname)
  if (reason === 'page' && hasIntroducedPageThisSession(pageId)) return
  if (!text) return

  markPageIntroduced(pageId)

  // 主动介绍：只播 TTS + 底部中文字幕，不强制拉开聊天面板（面板像工作台会显「错」）
  const last = agentStore.messages[agentStore.messages.length - 1]
  if (!(last && last.role === 'assistant' && last.content === text)) {
    agentStore.addMessage({
      id: `corp-intro-${pageId}-${Date.now()}`,
      role: 'assistant',
      content: text,
      timestamp: Date.now(),
    })
  }

  const seq = ++introSeq
  introSpeaking.value = true
  try {
    await speakCorpIntro(text)
  } finally {
    if (seq === introSeq) introSpeaking.value = false
  }
}

function scheduleProactiveIntro(reason: 'consent' | 'page', delayMs = 600) {
  if (introTimer != null) {
    window.clearTimeout(introTimer)
    introTimer = null
  }
  introTimer = window.setTimeout(() => {
    introTimer = null
    void runProactivePageIntro(reason)
  }, delayMs)
}

function onConsentAgreed() {
  agentStore.grantConsent()
  flushPendingIntakeFill()
  scheduleProactiveIntro('consent', 480)
}

function onProactiveIntroChange(enabled: boolean) {
  if (!enabled) {
    stopCorpIntroSpeech()
    introSpeaking.value = false
  }
}

/** 联系页右侧是问卷主栏，管家改锚定左下角避免遮挡选项 */
const isContactPage = computed(() => {
  if (typeof window === 'undefined') return false
  const p = window.location.pathname
  return /\/contact(?:\.html)?\/?$/i.test(p)
})

const isMobileViewport = ref(isCorpMobileViewport())

const showMobileContactIntake = computed(
  () => isContactPage.value && isMobileViewport.value,
)

function onMobileMqChange() {
  isMobileViewport.value = isCorpMobileViewport()
}

function onViewportResize() {
  const p = saveCorpBallPosition(position.value.x, position.value.y)
  agentStore.savePosition(p.x, p.y)
}

function onIntakeAssist(ev: Event) {
  const detail =
    (ev as CustomEvent<{ message?: string; prompt?: string; filled?: boolean }>).detail || {}
  if (detail.filled) {
    if (agentStore.consentGiven) {
      agentStore.openPanel()
    }
    return
  }
  const action: QuickAction = {
    label: 'AI 一键填单',
    task: 'intake_fill',
    message: detail.message || '请根据公司与系统类型预填需求问卷',
  }
  if (detail.prompt?.trim()) {
    action.payload = { prompt: detail.prompt.trim() }
  }
  if (!agentStore.consentGiven) {
    pendingIntakeAction.value = action
    agentStore.showPermissionDialog = true
    return
  }
  agentStore.openPanel()
  void runIntakeTask(action)
}

function tryAutoOpenMobileContactButler() {
  if (typeof window === 'undefined') return
  if (!isContactPagePath(window.location.pathname)) return
  if (!isCorpMobileViewport()) return
  try {
    if (sessionStorage.getItem('xc-contact-butler-intro-v2') === '1') return
    sessionStorage.setItem('xc-contact-butler-intro-v2', '1')
  } catch {
    return
  }
  window.setTimeout(() => {
    agentStore.openPanel()
  }, 700)
}

onMounted(() => {
  window.addEventListener('resize', onViewportResize)
  window.addEventListener('xc-corp-intake-assist', onIntakeAssist)
  const mq = window.matchMedia('(max-width: 960px)')
  mq.addEventListener('change', onMobileMqChange)
  tryAutoOpenMobileContactButler()
  // 已同意且开启主动介绍：进页后自动讲一嘴（每页每会话一次）
  if (agentStore.consentGiven && isCorpProactiveIntroEnabled()) {
    scheduleProactiveIntro('page', 900)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onViewportResize)
  window.removeEventListener('xc-corp-intake-assist', onIntakeAssist)
  window.matchMedia('(max-width: 960px)').removeEventListener('change', onMobileMqChange)
  if (introTimer != null) window.clearTimeout(introTimer)
  stopCorpIntroSpeech()
  introSpeaking.value = false
})
</script>

<style>
.panel-pop-enter-active {
  transition: all 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.panel-pop-leave-active {
  transition: all 0.18s ease;
}
.panel-pop-enter-from,
.panel-pop-leave-to {
  opacity: 0;
  transform: scale(0.92) translateY(8px);
}

/* Teleport 到 body 后仅作包装，不铺满视口 */
.butler-float-root--corp {
  --corp-ball-bottom: 24px;
  --corp-ball-w: 72px;
  --corp-ball-h: 88px;
  --corp-panel-gap: 10px;
  position: relative;
  z-index: 20000;
  pointer-events: none;
}

.butler-float-root--corp .butler-ball,
.butler-float-root--corp .butler-panel,
.butler-float-root--corp .perm-overlay {
  pointer-events: auto !important;
}

.butler-float-root--corp .butler-panel.butler-panel--corp-anchor {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.butler-float-root--corp.butler-float-root--speaking .butler-ball__logo-wrap {
  animation: corp-ball-pulse 1.1s ease-in-out infinite;
}

@keyframes corp-ball-pulse {
  0%,
  100% {
    transform: scale(1);
    filter: drop-shadow(0 0 0 transparent);
  }
  50% {
    transform: scale(1.06);
    filter: drop-shadow(0 0 10px rgba(37, 99, 235, 0.45));
  }
}
</style>
