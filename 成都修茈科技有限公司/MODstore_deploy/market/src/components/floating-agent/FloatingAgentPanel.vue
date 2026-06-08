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
      <div class="panel-head__left">
        <img
          class="panel-head__logo"
          :src="brandLogoUrl"
          alt=""
          width="28"
          height="28"
          decoding="async"
        />
        <div class="panel-head__titles">
          <span class="panel-head__title">AI 管家</span>
          <span class="panel-head__sub">{{ corpMode ? '官网咨询助手' : '当前页面助手' }}</span>
        </div>
      </div>
      <div class="panel-head__actions" @pointerdown.stop>
        <button
          v-if="!corpMode"
          type="button"
          class="panel-icon-btn"
          aria-label="查看操作日志"
          title="操作日志"
          @click.stop="showLog = !showLog"
        >
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M9 12h6M9 8h6M9 16h4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" stroke-width="1.6"/></svg>
        </button>
        <button
          type="button"
          class="panel-icon-btn"
          aria-label="清空对话"
          title="清空对话"
          @click.stop="agentStore.clearMessages()"
        >
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        <button
          type="button"
          class="panel-icon-btn"
          aria-label="关闭管家"
          title="关闭"
          @click.stop="agentStore.closePanel()"
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>
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
      <template v-if="corpMode">
        <div class="panel-composer panel-composer--corp">
          <AgentVoiceInput
            :voice-state="voiceState"
            :is-supported="voiceIsSupported"
            :error="voiceError"
            :loading-hint="voiceLoadingHint"
            :session-ready="voiceSessionReady"
            @toggle="toggleVoice"
          />
          <textarea
            ref="textareaRef"
            v-model="draft"
            class="panel-input"
            placeholder="说点什么…"
            rows="1"
            aria-label="发送消息"
            @keydown.enter.exact.prevent="sendText"
            @input="autoResize"
          />
          <button
            type="button"
            class="panel-send"
            :disabled="!draft.trim() || agentStore.isLoading"
            aria-label="发送"
            @click="sendText"
          >
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </div>
      </template>
      <template v-else>
        <AgentVoiceInput
          :voice-state="voiceState"
          :is-supported="voiceIsSupported"
          :error="voiceError"
          :loading-hint="voiceLoadingHint"
          :session-ready="voiceSessionReady"
          @toggle="toggleVoice"
        />
        <div class="panel-composer">
          <textarea
            ref="textareaRef"
            v-model="draft"
            class="panel-input"
            placeholder="说点什么…"
            rows="1"
            aria-label="发送消息"
            @keydown.enter.exact.prevent="sendText"
            @input="autoResize"
          />
          <button
            type="button"
            class="panel-send"
            :disabled="!draft.trim() || agentStore.isLoading"
            aria-label="发送"
            @click="sendText"
          >
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </div>
        <label
          class="panel-screenshot-toggle"
          title="是否附带截图发给 AI（需 vision 模型）"
        >
          <input v-model="withScreenshot" type="checkbox" />
          <span>附带截图</span>
        </label>
      </template>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useAgentStore } from '../../stores/agent'
import { useWorkbenchTheme } from '../../composables/useWorkbenchTheme'
import type { AgentHandleInputFn } from '../../composables/agent/agentEngineInjection'
import { useVoiceInput } from '../../composables/agent/useVoiceInput'
import { getActionLog } from '../../composables/agent/useActionExecutor'
import { saveCorpBallPosition } from '../../corp-butler/corpBallPosition'
import AgentStatusBar from './AgentStatusBar.vue'
import AgentChatHistory from './AgentChatHistory.vue'
import ButlerFilesDrawer from './ButlerFilesDrawer.vue'
import { useButlerWorkbenchTrayStore } from '../../stores/butlerWorkbenchTray'
import { useButlerDownloadHistoryStore } from '../../stores/butlerDownloadHistory'
import AgentVoiceInput from './AgentVoiceInput.vue'

import type { QuickAction } from '../../content/siteKnowledge'

const props = withDefaults(
  defineProps<{
    corpMode?: boolean
    handleInput: AgentHandleInputFn
    runIntakeTask?: (action: QuickAction) => Promise<void>
  }>(),
  { corpMode: false },
)

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
const withScreenshot = ref(false)
const showLog = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const panelRef = ref<HTMLDivElement | null>(null)

const actionLog = computed(() => getActionLog().slice().reverse())

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

// 语音输入
const {
  state: voiceState,
  error: voiceError,
  isSupported: voiceIsSupported,
  interimText: voiceInterimText,
  loadingHint: voiceLoadingHint,
  sessionReady: voiceSessionReady,
  startListening,
  stopListening: stopVoiceListening,
  speak,
} = useVoiceInput(async (text: string) => {
  draft.value = ''
  await sendMessage(text)
  if (props.corpMode) return
  const msgs = agentStore.messages
  const last = msgs[msgs.length - 1]
  if (last && last.role === 'assistant' && !last.isLoading) {
    await speak(last.content)
  }
})

watch(voiceInterimText, (t) => {
  if (voiceState.value === 'listening' && t) {
    draft.value = t
    nextTick(() => autoResize())
  }
})

function toggleVoice() {
  if (voiceState.value === 'listening') {
    void stopVoiceListening()
  } else {
    voiceError.value = ''
    startListening()
  }
}

async function sendText() {
  const text = draft.value.trim()
  if (!text) return
  draft.value = ''
  await nextTick()
  autoResize()
  await sendMessage(text)
}

async function sendMessage(text: string) {
  await handleInput(text, { withScreenshot: withScreenshot.value })
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

function autoResize() {
  const ta = textareaRef.value
  if (!ta) return
  ta.style.height = 'auto'
  ta.style.height = Math.min(ta.scrollHeight, 80) + 'px'
}
</script>

<style scoped>
.butler-panel {
  position: fixed;
  z-index: 11010;
  pointer-events: auto;
  background: rgba(10, 11, 15, 0.98);
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: 14px;
  box-shadow:
    0 18px 54px rgba(0, 0, 0, 0.58),
    0 0 0 1px rgba(255, 255, 255, 0.03);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  backdrop-filter: blur(14px);
}

.butler-panel.butler-panel--corp-anchor {
  top: 0;
  left: 0;
  right: auto;
  bottom: auto;
  width: 340px;
  height: min(420px, calc(100dvh - 120px));
  max-height: min(420px, calc(100dvh - 120px));
  min-height: 0;
  z-index: 20002;
}

.butler-panel.butler-panel--corp-anchor .panel-head {
  cursor: grab;
  flex-shrink: 0;
}

.butler-panel.butler-panel--corp-anchor .panel-head:active,
.butler-panel.butler-panel--corp-anchor .panel-head.panel-head--corp-drag:active {
  cursor: grabbing;
}

.butler-panel.butler-panel--corp-anchor :deep(.chat-history) {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

.butler-panel.butler-panel--corp-anchor .panel-foot {
  flex-shrink: 0;
  margin-top: auto;
}

.butler-panel.butler-panel--corp-anchor .panel-foot--corp {
  padding-top: 6px;
}

.butler-panel.butler-panel--corp-anchor .panel-composer--corp {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  width: 100%;
}

.butler-panel.butler-panel--corp-anchor .panel-composer--corp :deep(.voice-bar) {
  flex-shrink: 0;
  margin: 0;
}

.butler-panel.butler-panel--corp-anchor .panel-composer--corp :deep(.voice-hint),
.butler-panel.butler-panel--corp-anchor .panel-composer--corp :deep(.voice-err) {
  display: none;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 46px;
  padding: 8px 10px 8px 12px;
  cursor: grab;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  user-select: none;
}

.panel-head:active { cursor: grabbing; }

.panel-head__left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-head__logo {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  object-fit: contain;
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.panel-head__titles {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.panel-head__title {
  font-size: 0.86rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.9);
  letter-spacing: 0.02em;
}

.panel-head__sub {
  font-size: 0.68rem;
  color: rgba(255, 255, 255, 0.36);
}

.panel-head__actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.panel-icon-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.36);
  cursor: pointer;
  font-size: 1.1rem;
  transition: all 0.15s;
}

.panel-icon-btn svg { width: 15px; height: 15px; }

.panel-icon-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.85);
}

/* 操作日志 */
.panel-log {
  padding: 8px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  max-height: 120px;
  overflow-y: auto;
  background: rgba(255, 255, 255, 0.02);
}

.panel-log__title {
  font-size: 0.72rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.4);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.panel-log__empty {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.25);
}

.panel-log__entry {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.73rem;
  color: rgba(255, 255, 255, 0.55);
  padding: 2px 0;
}

.log-action {
  color: #7dd3fc;
  font-weight: 600;
  flex-shrink: 0;
}

.log-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-status { flex-shrink: 0; font-weight: 600; }
.log-status--ok { color: #4ade80; }
.log-status--err { color: #f87171; }

/* 底部输入区 */
.panel-foot {
  padding: 8px 10px 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.panel-composer {
  display: flex;
  align-items: flex-end;
  gap: 6px;
}

.panel-input {
  flex: 1;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 9px;
  padding: 8px 10px;
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.88);
  resize: none;
  outline: none;
  line-height: 1.4;
  font-family: inherit;
  min-height: 36px;
  max-height: 80px;
  transition: border-color 0.15s;
}

.panel-input::placeholder { color: rgba(255, 255, 255, 0.25); }
.panel-input:focus { border-color: rgba(148, 163, 184, 0.38); }

.panel-send {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(59, 130, 246, 0.26);
  border: 1px solid rgba(96, 165, 250, 0.28);
  border: none;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
}

.panel-send svg { width: 16px; height: 16px; color: #fff; }
.panel-send:hover:not(:disabled) { background: rgba(59, 130, 246, 0.38); }
.panel-send:disabled { opacity: 0.4; cursor: not-allowed; }

.panel-screenshot-toggle {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.34);
  cursor: pointer;
  user-select: none;
  align-self: flex-end;
}

.panel-screenshot-toggle input { accent-color: #64748b; cursor: pointer; }
.panel-screenshot-toggle:hover { color: rgba(255, 255, 255, 0.55); }

/* 浅色工作台：与「智能对话」悬浮窗一致 */
.butler-panel.butler-panel--light {
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid rgba(147, 197, 253, 0.55);
  border-radius: 18px;
  box-shadow:
    0 22px 52px rgba(15, 76, 129, 0.22),
    0 8px 18px rgba(37, 99, 235, 0.12);
  backdrop-filter: none;
}

.butler-panel--light .panel-head {
  padding: 12px 12px 10px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.92);
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.98), rgba(255, 255, 255, 0.96));
}

.butler-panel--light .panel-head__logo {
  border-color: rgba(24, 144, 255, 0.36);
  box-shadow: 0 2px 8px rgba(15, 76, 129, 0.1);
}

.butler-panel--light .panel-head__title {
  font-size: 14px;
  font-weight: 800;
  color: #172033;
}

.butler-panel--light .panel-head__sub {
  font-size: 11px;
  color: rgba(71, 85, 105, 0.72);
}

.butler-panel--light .panel-icon-btn {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  color: #64748b;
}

.butler-panel--light .panel-icon-btn:hover {
  background: rgba(219, 234, 254, 0.72);
  color: #1e3a8a;
}

.butler-panel--light .panel-log {
  border-bottom-color: rgba(226, 232, 240, 0.92);
  background: rgba(248, 250, 252, 0.9);
}

.butler-panel--light .panel-log__title {
  color: #64748b;
}

.butler-panel--light .panel-log__empty,
.butler-panel--light .panel-log__entry {
  color: #475569;
}

.butler-panel--light .panel-foot {
  border-top-color: rgba(226, 232, 240, 0.92);
  background: rgba(255, 255, 255, 0.96);
}

.butler-panel--light .panel-input {
  background: #f8fafc;
  border-color: rgba(148, 163, 184, 0.45);
  color: #1e293b;
}

.butler-panel--light .panel-input::placeholder {
  color: #94a3b8;
}

.butler-panel--light .panel-input:focus {
  border-color: rgba(37, 99, 235, 0.45);
}

.butler-panel--light .panel-send {
  background: #2563eb;
  border: none;
}

.butler-panel--light .panel-send:hover:not(:disabled) {
  background: #1d4ed8;
}

.butler-panel--light .panel-screenshot-toggle {
  color: #64748b;
}

.butler-panel--light .panel-screenshot-toggle:hover {
  color: #334155;
}

.butler-panel--light :deep(.status-bar) {
  border-bottom-color: rgba(226, 232, 240, 0.92);
}

.butler-panel--light :deep(.chat-empty) {
  color: #64748b;
  border-color: rgba(148, 163, 184, 0.35);
  background: rgba(241, 245, 249, 0.75);
}

.butler-panel--light :deep(.chat-empty-title) {
  color: #172033;
}

.butler-panel--light :deep(.chat-empty-desc) {
  color: #64748b;
}

.butler-panel--light :deep(.quick-tip) {
  background: #fff;
  border-color: rgba(148, 163, 184, 0.4);
  color: #334155;
}

.butler-panel--light :deep(.quick-tip:hover) {
  background: #eff6ff;
  border-color: rgba(37, 99, 235, 0.35);
  color: #1e3a8a;
}

.butler-panel--light :deep(.corp-welcome) {
  background: rgba(241, 245, 249, 0.92);
  border-color: rgba(148, 163, 184, 0.32);
}

.butler-panel--light :deep(.corp-welcome__title) {
  color: #0f172a;
}

.butler-panel--light :deep(.corp-welcome__subtitle) {
  color: #475569;
}

.butler-panel--light :deep(.corp-task-card) {
  background: #f8fafc;
  border-color: rgba(15, 23, 42, 0.08);
}

.butler-panel--light :deep(.corp-task-card:hover) {
  background: #f1f5f9;
  border-color: rgba(11, 99, 246, 0.22);
}

.butler-panel--light :deep(.bubble--assistant) {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #1e293b;
}

.butler-panel--light :deep(.bubble-text strong) {
  color: #0f172a;
}

.butler-panel--light :deep(.bubble--tool) {
  background: #eff6ff;
  border-color: rgba(37, 99, 235, 0.2);
  color: #1e40af;
}

.butler-panel--light :deep(.bubble-time) {
  color: #94a3b8;
}

.butler-panel--light :deep(.voice-btn) {
  border-color: rgba(148, 163, 184, 0.5);
  background: #f1f5f9;
  color: #475569;
}

.butler-panel--light :deep(.voice-btn:hover) {
  background: #e2e8f0;
  color: #1e3a8a;
}

.butler-panel--light :deep(.voice-btn--active) {
  background: rgba(37, 99, 235, 0.12);
  border-color: rgba(37, 99, 235, 0.5);
  color: #2563eb;
}
</style>
