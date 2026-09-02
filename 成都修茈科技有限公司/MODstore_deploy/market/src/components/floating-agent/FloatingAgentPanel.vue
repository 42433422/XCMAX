<template>
  <div
    ref="panelRef"
    class="butler-panel"
    :class="{
      'butler-panel--light': corpMode || isLightTheme,
      'butler-panel--corp-anchor': corpMode,
    }"
    :style="panelStyle"
    role="dialog"
    aria-label="AI 数字管家"
    aria-modal="false"
  >
    <!-- 顶栏（可拖拽）-->
    <header
      class="panel-head"
      :class="{ 'panel-head--corp-drag': corpMode }"
      :title="corpMode ? '按住标题栏可拖动' : undefined"
      @pointerdown="onHeaderPointerDown"
      @pointermove="onHeaderPointerMove"
      @pointerup="onHeaderPointerUp"
    >
      <PanelHeader
        :corp-mode="corpMode"
        :brand-logo-url="brandLogoUrl"
        :proactive-intro-on="proactiveIntroOn"
        @toggle-proactive-intro="toggleProactiveIntro"
        @toggle-log="showLog = !showLog"
        @clear-messages="agentStore.clearMessages()"
        @close="agentStore.closePanel()"
      />
    </header>

    <!-- 状态条 -->
    <AgentStatusBar v-if="!corpMode" :mode="mode" @stop="agentStore.setMode('idle')" />

    <ButlerFilesDrawer v-if="!corpMode && showFilesDrawer" ref="filesDrawerRef" />

    <!-- 操作日志抽屉 -->
    <div v-if="!corpMode && showLog" class="panel-log">
      <div class="panel-log__title">操作日志</div>
      <div v-if="!actionLog.length" class="panel-log__empty">暂无操作记录</div>
      <div v-for="(entry, i) in actionLog" :key="i" class="panel-log__entry">
        <span class="log-action">{{ entry.action }}</span>
        <span class="log-label">{{ entry.label }}</span>
        <span :class="['log-status', entry.success ? 'log-status--ok' : 'log-status--err']">
          {{ entry.success ? '成功' : '失败' }}
        </span>
      </div>
    </div>

    <!-- 对话区 -->
    <AgentChatHistory
      :corp-mode="corpMode"
      @quick="handleQuick"
      @task="handleIntakeTask"
    />

    <!-- 输入区：官网模式单行（麦+输入+发送），避免输入条挤在标题下 -->
    <footer class="panel-foot" :class="{ 'panel-foot--corp': corpMode }">
      <input
        ref="imageInputRef"
        type="file"
        accept="image/*"
        class="panel-image-input"
        tabindex="-1"
        aria-hidden="true"
        @change="onImagePicked"
      />
      <div v-if="pendingImageDataUrl" class="panel-attach-preview" :class="{ 'panel-attach-preview--light': isLightTheme || corpMode }">
        <img :src="pendingImageDataUrl" alt="待发送图片" class="panel-attach-preview__img" />
        <button type="button" class="panel-attach-preview__clear" aria-label="移除图片" title="移除图片" @click="clearPendingImage">
          ×
        </button>
      </div>
      <p v-if="imagePickError" class="panel-attach-error" role="alert">{{ imagePickError }}</p>
      <PanelComposer
        ref="composerRef"
        v-model:draft="draft"
        :corp-mode="corpMode"
        :is-light-theme="isLightTheme"
        :has-pending-image="!!pendingImageDataUrl"
        :image-picking="imagePicking"
        :voice-state="voiceState"
        :is-supported="voiceIsSupported"
        :error="voiceError"
        :loading-hint="voiceLoadingHint"
        :session-ready="voiceSessionReady"
        @toggle-voice="toggleVoice"
        @pick-image="openImagePicker"
        @send="sendText"
      />
    </footer>
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：顶栏/输入区子组件与图片、语音 composables 在 ./floating-agent-panel/，样式在 ./floating-agent-panel/floatingAgentPanel.css。
import { ref, computed, nextTick, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useAgentStore } from '../../stores/agent'
import { useWorkbenchTheme } from '../../composables/useWorkbenchTheme'
import type { AgentHandleInputFn } from '../../composables/agent/agentEngineInjection'
import { getActionLog } from '../../composables/agent/useActionExecutor'
import { saveCorpBallPosition } from '../../corp-butler/corpBallPosition'
import {
  isCorpProactiveIntroEnabled,
  setCorpProactiveIntroEnabled,
  stopCorpIntroSpeech,
} from '../../corp-butler/corpPageIntro'
import AgentStatusBar from './AgentStatusBar.vue'
import AgentChatHistory from './AgentChatHistory.vue'
import ButlerFilesDrawer from './ButlerFilesDrawer.vue'
import { useButlerWorkbenchTrayStore } from '../../stores/butlerWorkbenchTray'
import { useButlerDownloadHistoryStore } from '../../stores/butlerDownloadHistory'

import type { QuickAction } from '../../content/siteKnowledge'
import PanelHeader from './floating-agent-panel/PanelHeader.vue'
import PanelComposer from './floating-agent-panel/PanelComposer.vue'
import { useAgentPanelImage } from './floating-agent-panel/useAgentPanelImage'
import { useAgentPanelVoice } from './floating-agent-panel/useAgentPanelVoice'

const props = withDefaults(
  defineProps<{
    corpMode?: boolean
    handleInput: AgentHandleInputFn
    runIntakeTask?: (action: QuickAction) => Promise<void>
  }>(),
  { corpMode: false, runIntakeTask: undefined },
)

const emit = defineEmits<{
  (e: 'proactive-intro-change', enabled: boolean): void
}>()

const proactiveIntroOn = ref(isCorpProactiveIntroEnabled())

function toggleProactiveIntro() {
  const next = !proactiveIntroOn.value
  proactiveIntroOn.value = next
  setCorpProactiveIntroEnabled(next)
  if (!next) stopCorpIntroSpeech()
  emit('proactive-intro-change', next)
}

const agentStore = useAgentStore()
const trayStore = useButlerWorkbenchTrayStore()
const historyStore = useButlerDownloadHistoryStore()
const { mode, position, focusFilesDrawer } = storeToRefs(agentStore)
const { overflowCount } = storeToRefs(trayStore)
const filesDrawerRef = ref<InstanceType<typeof ButlerFilesDrawer> | null>(null)

const showFilesDrawer = computed(
  () => overflowCount.value > 0 || historyStore.records.length > 0,
)

watch(focusFilesDrawer, (focus) => {
  if (!focus) return
  void nextTick(() => {
    const el = filesDrawerRef.value?.$el as HTMLElement | undefined
    el?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
    agentStore.clearFilesDrawerFocus()
  })
})
const { isLightTheme } = useWorkbenchTheme()
const brandLogoUrl = computed(() =>
  props.corpMode ? '/corp-butler/brand-xc-logo.jpg' : `${import.meta.env.BASE_URL}brand-xc-logo.jpg`,
)

const handleInput = props.handleInput

const draft = ref('')
const showLog = ref(false)
const panelRef = ref<HTMLDivElement | null>(null)
const composerRef = ref<InstanceType<typeof PanelComposer> | null>(null)

const {
  pendingImageDataUrl, imagePickError, imagePicking, imageInputRef,
  openImagePicker, clearPendingImage, onImagePicked,
} = useAgentPanelImage()

const actionLog = computed(() => getActionLog().slice().reverse())

async function sendMessage(text: string, imageDataUrl?: string | null) {
  await handleInput(text, { imageDataUrl: imageDataUrl || null })
}

const {
  voiceState, voiceError, voiceIsSupported, voiceLoadingHint, voiceSessionReady, toggleVoice,
} = useAgentPanelVoice({
  draft,
  corpMode: () => props.corpMode,
  sendMessage,
  requestResize: () => composerRef.value?.autoResize?.(),
})

async function sendText() {
  const text = draft.value.trim()
  const imageDataUrl = pendingImageDataUrl.value
  if (!text && !imageDataUrl) return
  draft.value = ''
  pendingImageDataUrl.value = null
  imagePickError.value = ''
  await nextTick()
  composerRef.value?.autoResize?.()
  await sendMessage(text, imageDataUrl)
}

async function handleQuick(text: string) {
  await sendMessage(text)
}

async function handleIntakeTask(action: QuickAction) {
  if (props.runIntakeTask) {
    await props.runIntakeTask(action)
    return
  }
  const text = action.message || action.label
  if (text) await sendMessage(text)
}

// 面板定位：始终在球的上方（官网模式高度由 CSS --corp-anchor 控制，避免 inline height 挤没对话区）
const panelStyle = computed(() => {
  const bx = position.value.x
  const by = position.value.y
  const panelW = 340
  const panelH = props.corpMode ? 420 : 460
  const margin = 12

  let left = bx + 32 - panelW / 2
  let top = by - panelH - margin

  // 边界保护
  left = Math.max(8, Math.min(window.innerWidth - panelW - 8, left))
  top = Math.max(8, Math.min(window.innerHeight - panelH - 8, top))

  const base = {
    left: `${left}px`,
    top: `${top}px`,
    width: `${panelW}px`,
  }
  if (props.corpMode) return base
  return { ...base, height: `${panelH}px` }
})

// 面板拖拽
let panelDragStartX = 0
let panelDragStartY = 0
let isPanelDragging = false

function onHeaderPointerDown(e: PointerEvent) {
  if (e.button !== 0) return
  isPanelDragging = true
  panelDragStartX = e.clientX
  panelDragStartY = e.clientY
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

function onHeaderPointerMove(e: PointerEvent) {
  if (!isPanelDragging) return
  const dx = e.clientX - panelDragStartX
  const dy = e.clientY - panelDragStartY
  panelDragStartX = e.clientX
  panelDragStartY = e.clientY
  if (props.corpMode) {
    const p = saveCorpBallPosition(position.value.x + dx, position.value.y + dy)
    agentStore.savePosition(p.x, p.y)
    return
  }
  agentStore.savePosition(position.value.x + dx, position.value.y + dy)
}

function onHeaderPointerUp() {
  isPanelDragging = false
}
</script>

<style scoped src="./floating-agent-panel/floatingAgentPanel.css"></style>
