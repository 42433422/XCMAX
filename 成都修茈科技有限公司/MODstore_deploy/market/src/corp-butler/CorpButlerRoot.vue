<template>
  <Teleport to="body">
    <div
      class="butler-float-root butler-float-root--corp"
      :class="{ 'butler-float-root--contact-page': isContactPage }"
    >
      <AgentPermissionDialog
        v-if="showPermissionDialog"
        @agree="onIntakeAssistAgreed"
        @dismiss="agentStore.dismissLater()"
      />

      <FloatingAgentBall :is-speaking="false" force-light corp-mode />
      <Transition name="panel-pop">
        <FloatingAgentPanel
          v-if="isOpen"
          corp-mode
          :handle-input="handleInput"
          :run-intake-task="runIntakeTask"
        />
      </Transition>

      <CorpContactIntakeModal v-if="showMobileContactIntake" />
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useAgentStore } from '../stores/agent'
import { clampCorpBallPosition, saveCorpBallPosition } from './corpBallPosition'
import { isCorpMobileViewport } from './corpViewport'
import { useCorpAgentEngine } from '../composables/agent/useCorpAgentEngine'
import { isContactPagePath } from '../content/siteKnowledge'
import type { QuickAction } from '../content/siteKnowledge'
import AgentPermissionDialog from '../components/floating-agent/AgentPermissionDialog.vue'
import FloatingAgentBall from '../components/floating-agent/FloatingAgentBall.vue'
import FloatingAgentPanel from '../components/floating-agent/FloatingAgentPanel.vue'
import CorpContactIntakeModal from '../components/floating-agent/CorpContactIntakeModal.vue'

const agentStore = useAgentStore()
const { isOpen, showPermissionDialog, position } = storeToRefs(agentStore)
const { handleInput, runIntakeTask } = useCorpAgentEngine()
const pendingIntakeAction = ref<QuickAction | null>(null)

function flushPendingIntakeFill() {
  const action = pendingIntakeAction.value
  if (!action) return
  pendingIntakeAction.value = null
  agentStore.openPanel()
  void runIntakeTask(action)
}

function onIntakeAssistAgreed() {
  agentStore.grantConsent()
  flushPendingIntakeFill()
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
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onViewportResize)
  window.removeEventListener('xc-corp-intake-assist', onIntakeAssist)
  window.matchMedia('(max-width: 960px)').removeEventListener('change', onMobileMqChange)
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
  --corp-ball-size: 52px;
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
</style>
