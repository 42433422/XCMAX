<template>
  <div class="butler-float-root">
    <!-- 隐私同意弹窗 -->
    <AgentPermissionDialog
      v-if="showPermissionDialog"
      @agree="agentStore.grantConsent()"
      @dismiss="agentStore.dismissLater()"
    />

    <!-- 主动建议气泡 -->
    <AgentSuggestionToast
      :suggestion="currentSuggestion"
      @dismiss="dismiss"
      @open-panel="agentStore.openPanel()"
    />

    <!-- 悬浮球 -->
    <FloatingAgentBall :is-speaking="isSpeaking" />

    <!-- 对话面板 -->
    <Transition name="panel-pop">
      <FloatingAgentPanel v-if="isOpen" :handle-input="handleInput" />
    </Transition>

    <!-- vibe-coding 改写进度全屏遮罩 -->
    <ButlerProgressOverlay
      v-if="orchestrationSession"
      @done="onOrchestratesDone"
      @rollback="onOrchestrationRollback"
      @close="agentStore.clearOrchestration()"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useAgentStore } from '../../stores/agent'
import { useAgentSuggestions } from '../../composables/agent/useAgentSuggestions'
import { useAgentEngine } from '../../composables/agent/useAgentEngine'
import { useESkillRuntime } from '../../composables/agent/useESkillRuntime'
import { useButlerOrchestrator } from '../../composables/agent/useButlerOrchestrator'
import { registerBuiltinSkills } from '../../composables/agent/skills/index'
import {
  subscribeButlerTask,
  buildButlerTaskPrompt,
  type ButlerTaskPublishEvent,
} from '../../utils/agent/butlerTaskBus'
import AgentPermissionDialog from './AgentPermissionDialog.vue'
import AgentSuggestionToast from './AgentSuggestionToast.vue'
import FloatingAgentBall from './FloatingAgentBall.vue'
import FloatingAgentPanel from './FloatingAgentPanel.vue'
import ButlerProgressOverlay from './ButlerProgressOverlay.vue'

const agentStore = useAgentStore()
const { isOpen, showPermissionDialog, orchestrationSession } = storeToRefs(agentStore)
const isSpeaking = ref(false)
const { handleInput } = useAgentEngine()

const router = useRouter()
const orchestrator = useButlerOrchestrator()
let unsubscribeTaskBus: (() => void) | null = null
let busTaskQueue = Promise.resolve()

// 注册内置技能
onMounted(() => {
  registerBuiltinSkills(router)
  unsubscribeTaskBus = subscribeButlerTask((event) => {
    busTaskQueue = busTaskQueue
      .then(() => consumeTaskBusEvent(event))
      .catch(() => undefined)
  })
})
onBeforeUnmount(() => {
  if (!unsubscribeTaskBus) return
  unsubscribeTaskBus()
  unsubscribeTaskBus = null
})

// E-Skill 运行时（Phase 4）
useESkillRuntime()

// 主动建议
const { currentSuggestion, dismiss } = useAgentSuggestions()

async function consumeTaskBusEvent(event: ButlerTaskPublishEvent): Promise<void> {
  if (!event.employeeId || !event.brief) return
  if (!agentStore.consentGiven) {
    agentStore.showPermissionDialog = true
    return
  }
  agentStore.openPanel()
  await handleInput(buildButlerTaskPrompt(event), { withScreenshot: false })
}

function onOrchestratesDone() {
  agentStore.clearOrchestration()
  orchestrator.refreshAfterDone()
}

function onOrchestrationRollback() {
  agentStore.clearOrchestration()
}
</script>

<style>
/* 根节点不挡主工作台点击；仅球与面板可交互 */
.butler-float-root {
  pointer-events: none;
}
.butler-float-root > * {
  pointer-events: auto;
}

/* panel 弹出动画 */
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
</style>
