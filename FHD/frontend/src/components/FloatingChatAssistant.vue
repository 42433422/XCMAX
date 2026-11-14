<template>
  <div
    v-if="props.visible && (!externallyHidden || voiceCallActive)"
    ref="rootRef"
    class="floating-chat-root"
    :class="{ dragging: isDragging }"
    :style="rootStyle"
  >
    <button
      class="floating-chat-toggle"
      :class="{ 'floating-chat-toggle--admin': props.maleAvatar, 'floating-chat-toggle--calling': callOpen }"
      type="button"
      :aria-expanded="isOpen ? 'true' : 'false'"
      aria-controls="floating-chat-panel"
      aria-label="小C助理"
      title="小C助理"
      @pointerdown="onDragStart"
      @click="toggleOpen"
    >
      <span class="floating-chat-toggle-avatar" aria-hidden="true">
        <img :src="avatarUrl" alt="" draggable="false" width="42" height="42" decoding="async" />
      </span>
      <span
        v-if="callOpen"
        class="floating-chat-ball-actions"
        @pointerdown.stop
      >
        <span
          class="floating-chat-ball-action"
          role="button"
          tabindex="0"
          :title="callMuted ? '取消静音' : '静音'"
          :aria-label="callMuted ? '取消静音' : '静音'"
          @click.stop="toggleVoiceCallMute"
          @keydown.enter.prevent.stop="toggleVoiceCallMute"
          @keydown.space.prevent.stop="toggleVoiceCallMute"
        >
          <i class="fa" :class="callMuted ? 'fa-microphone' : 'fa-microphone-slash'" aria-hidden="true"></i>
        </span>
        <span
          class="floating-chat-ball-action"
          role="button"
          tabindex="0"
          :title="callSpeakerOn ? '关闭免提' : '开启免提'"
          :aria-label="callSpeakerOn ? '关闭免提' : '开启免提'"
          @click.stop="toggleVoiceCallSpeaker"
          @keydown.enter.prevent.stop="toggleVoiceCallSpeaker"
          @keydown.space.prevent.stop="toggleVoiceCallSpeaker"
        >
          <i class="fa" :class="callSpeakerOn ? 'fa-volume-up' : 'fa-volume-off'" aria-hidden="true"></i>
        </span>
        <span
          class="floating-chat-ball-action floating-chat-ball-action--hangup"
          role="button"
          tabindex="0"
          title="挂断"
          aria-label="挂断"
          @click.stop="hangUpVoiceCall"
          @keydown.enter.prevent.stop="hangUpVoiceCall"
          @keydown.space.prevent.stop="hangUpVoiceCall"
        >
          <i class="fa fa-phone" aria-hidden="true"></i>
        </span>
      </span>
      <span v-else class="floating-chat-toggle-label">小C助理</span>
    </button>

    <div
      v-if="isOpen"
      id="floating-chat-panel"
      class="floating-chat-panel"
      role="dialog"
      aria-modal="false"
      aria-labelledby="floating-chat-title"
    >
      <div class="floating-chat-header" @pointerdown="onDragStart">
        <div class="floating-chat-title-wrap">
          <div id="floating-chat-title" class="floating-chat-title">{{ callOpen ? '语音通话' : '小C助理' }}</div>
          <div v-if="callOpen" class="floating-chat-call-meta">{{ callDurationText }} · {{ callStatusText }}</div>
        </div>
        <button
          v-if="!callOpen"
          class="floating-chat-call-entry"
          type="button"
          aria-label="语音通话"
          title="语音通话"
          @click="startCallFromEntry"
        >
          <i class="fa fa-phone" aria-hidden="true"></i>
          <span class="floating-chat-call-entry-label">语音通话</span>
        </button>
        <button class="floating-chat-close" type="button" aria-label="关闭" @click="closePanel">×</button>
      </div>

      <div v-if="callOpen" class="floating-chat-call">
        <div class="floating-chat-call-stage" role="status" aria-live="polite">{{ callStatusText }}</div>
        <div class="floating-chat-call-captions">
          <div v-if="callHeardText" class="floating-chat-call-caption user">你说：{{ callHeardText }}</div>
          <div v-if="callReplyText" class="floating-chat-call-caption ai">小C：{{ callReplyText }}</div>
          <div v-if="callErrorText" class="floating-chat-call-caption error" role="alert">{{ callErrorText }}</div>
          <p v-if="!callHeardText && !callReplyText && !callErrorText" class="floating-chat-call-hint">
            请直接说话，小C 会自动回答。
          </p>
        </div>
      </div>

      <div v-else ref="messageListRef" class="floating-chat-messages">
        <div v-for="(msg, idx) in visibleMessages" :key="`${idx}-${msg.time}`" class="floating-chat-message" :class="msg.role">
          <div class="floating-chat-bubble" v-html="sanitizeChatBubbleHtml(msg.content)"></div>
          <div class="floating-chat-time">{{ msg.time }}</div>
        </div>
        <div v-if="isLoading && !isStreamingReply" class="floating-chat-message ai">
          <div class="floating-chat-bubble">{{ loadingProgressText }}</div>
        </div>
      </div>

      <form v-if="!callOpen" class="floating-chat-input-row" @submit.prevent="submitMessage">
        <textarea
          v-model.trim="draft"
          class="floating-chat-input"
          rows="2"
          placeholder="输入消息..."
          :disabled="isLoading"
          @keydown.enter.exact.prevent="submitMessage"
        ></textarea>
        <button class="floating-chat-send" type="submit" :disabled="!draft || isLoading">发送</button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useChatView } from '@/composables/useChatView'
import { useVoiceCall } from '@/composables/useVoiceCall'
import { requestVoiceCallStart, voiceCallActive } from '@/composables/voiceCallHost'
import { publicAssetUrl } from '@/utils/publicAssetUrl'
import { sanitizeChatBubbleHtml } from '@/utils/sanitizeHtml'
import { readAiSessionIdFromStorage, writeAiSessionIdToStorage } from '@/utils/chatStorageKeys'

const props = defineProps({
  visible: {
    type: Boolean,
    default: true,
  },
  /** 管理端（含其登录入口）使用男版；桌面端和客户端使用女版。 */
  maleAvatar: {
    type: Boolean,
    default: false,
  },
  /** 非智能对话页发起通话时展开面板；智能对话页只在悬浮球内通话。 */
  expandCallPanel: {
    type: Boolean,
    default: true,
  },
})

const avatarUrl = computed(() =>
  publicAssetUrl(props.maleAvatar ? 'ai-butler-male-avatar-v1.jpg' : 'ai-butler-female-avatar-v1.png'),
)

function generateSessionId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2)
}

const storedSessionId = readAiSessionIdFromStorage()
const currentSessionId = ref(storedSessionId || generateSessionId())
if (!storedSessionId) {
  writeAiSessionIdToStorage(currentSessionId.value)
}

const isOpen = ref(false)
const externallyHidden = ref(false)
const draft = ref('')
const messageListRef = ref<HTMLElement | null>(null)
const rootRef = ref<HTMLElement | null>(null)
const rootLeft = ref(0)
const rootTop = ref(0)
const isDragging = ref(false)
const hasDraggedSincePointerDown = ref(false)
const suppressNextToggleClick = ref(false)
/** 发起通话时是否展开面板：智能对话页只在悬浮球内通话。 */
const expandPanelOnCall = ref(true)
const dragPointerId = ref<number | null>(null)
const dragStartClientX = ref(0)
const dragStartClientY = ref(0)
const dragStartLeft = ref(0)
const dragStartTop = ref(0)
const DRAG_THRESHOLD_PX = 4
const EDGE_PADDING_PX = 8
const ROOT_MARGIN_PX = 22

const { messages, isLoading, isStreamingReply, loadingProgressText, sendMessage } = useChatView({
  sessionId: currentSessionId,
})

/** 语音通话：复用当前悬浮窗会话的发送与消息流，界面留在悬浮窗内。 */
const {
  open: callOpen,
  durationText: callDurationText,
  statusText: callStatusText,
  heardText: callHeardText,
  replyText: callReplyText,
  errorText: callErrorText,
  muted: callMuted,
  speakerOn: callSpeakerOn,
  start: startVoiceCall,
  hangUp: hangUpVoiceCall,
  toggleMute: toggleVoiceCallMute,
  toggleSpeaker: toggleVoiceCallSpeaker,
} = useVoiceCall({ sendMessage, messages, title: '小C助理' })

const visibleMessages = computed(() => messages.value.slice(-20))
const rootStyle = computed(() => ({
  left: `${rootLeft.value}px`,
  top: `${rootTop.value}px`,
}))

const closeFloatingChatPanel = () => {
  if (callOpen.value) hangUpVoiceCall()
  isOpen.value = false
}

const suppressFloatingChatPanel = () => {
  if (callOpen.value) hangUpVoiceCall()
  isOpen.value = false
  externallyHidden.value = true
}

/** 悬浮窗内入口只发起点话，实际通话由 'xcagi:start-voice-call' 统一开启。 */
const startCallFromEntry = () => {
  expandPanelOnCall.value = true
  isOpen.value = true
  requestVoiceCallStart()
}

const closePanel = () => {
  if (callOpen.value) hangUpVoiceCall()
  isOpen.value = false
}

const onStartVoiceCallRequest = (event?: Event) => {
  const detail = (event as CustomEvent<{ expandPanel?: boolean }> | undefined)?.detail
  expandPanelOnCall.value = props.expandCallPanel && detail?.expandPanel !== false
  isOpen.value = expandPanelOnCall.value
  startVoiceCall()
}

const restoreFloatingChatPanel = () => {
  externallyHidden.value = false
  void placeRootToBottomRight()
}

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

const clampRootPosition = (left: number, top: number) => {
  const root = rootRef.value
  if (!root) {
    return { left, top }
  }
  const rect = root.getBoundingClientRect()
  const maxLeft = Math.max(EDGE_PADDING_PX, window.innerWidth - rect.width - EDGE_PADDING_PX)
  const maxTop = Math.max(EDGE_PADDING_PX, window.innerHeight - rect.height - EDGE_PADDING_PX)
  return {
    left: clamp(left, EDGE_PADDING_PX, maxLeft),
    top: clamp(top, EDGE_PADDING_PX, maxTop),
  }
}

const placeRootToBottomRight = async () => {
  await nextTick()
  const root = rootRef.value
  if (!root) return
  const rect = root.getBoundingClientRect()
  rootLeft.value = Math.max(EDGE_PADDING_PX, window.innerWidth - rect.width - ROOT_MARGIN_PX)
  rootTop.value = Math.max(EDGE_PADDING_PX, window.innerHeight - rect.height - ROOT_MARGIN_PX)
}

const keepRootInViewport = () => {
  const normalized = clampRootPosition(rootLeft.value, rootTop.value)
  rootLeft.value = normalized.left
  rootTop.value = normalized.top
}

const onWindowResize = () => {
  if (isOpen.value) {
    void ensurePanelInViewport()
    return
  }
  keepRootInViewport()
}

/** 展开面板/通话时保证整块面板（含底部静音、免提、挂断）落在视口内。 */
const ensurePanelInViewport = async () => {
  await nextTick()
  const root = rootRef.value
  const panel = root?.querySelector('.floating-chat-panel') as HTMLElement | null
  if (!root || !panel) return
  const margin = 8
  const panelRect = panel.getBoundingClientRect()
  if (panelRect.top < margin) {
    rootTop.value = clamp(
      rootTop.value + (margin - panelRect.top),
      EDGE_PADDING_PX,
      Math.max(EDGE_PADDING_PX, window.innerHeight - root.offsetHeight - margin),
    )
  }
  const nextRect = panel.getBoundingClientRect()
  if (nextRect.top < margin) {
    await placeRootToBottomRight()
  }
}

const scrollToBottom = async () => {
  await nextTick()
  const el = messageListRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

/** 通话中按页面切换面板展开态：智能对话页收起，其它页面展开。 */
const syncCallPanelVisibility = () => {
  if (expandPanelOnCall.value) {
    isOpen.value = true
    void ensurePanelInViewport()
    return
  }
  isOpen.value = false
  void nextTick(() => keepRootInViewport())
}

const toggleOpen = async () => {
  if (suppressNextToggleClick.value) {
    suppressNextToggleClick.value = false
    return
  }
  // 通话中不收起面板，否则静音/挂断按钮会一起消失。
  if (callOpen.value && isOpen.value) return
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    await scrollToBottom()
    keepRootInViewport()
  }
}

const onDragStart = (event: PointerEvent) => {
  if (event.button !== 0) return
  if (!props.visible) return
  const eventTarget = event.target as HTMLElement | null
  if (eventTarget?.closest('.floating-chat-close')) return
  const target = event.currentTarget as HTMLElement | null
  if (!target) return
  dragPointerId.value = event.pointerId
  dragStartClientX.value = event.clientX
  dragStartClientY.value = event.clientY
  dragStartLeft.value = rootLeft.value
  dragStartTop.value = rootTop.value
  isDragging.value = false
  hasDraggedSincePointerDown.value = false
  target.setPointerCapture(event.pointerId)
  target.addEventListener('pointermove', onDragMove)
  target.addEventListener('pointerup', onDragEnd)
  target.addEventListener('pointercancel', onDragEnd)
}

const onDragMove = (event: PointerEvent) => {
  if (dragPointerId.value !== event.pointerId) return
  const deltaX = event.clientX - dragStartClientX.value
  const deltaY = event.clientY - dragStartClientY.value
  if (!hasDraggedSincePointerDown.value) {
    const distance = Math.hypot(deltaX, deltaY)
    if (distance < DRAG_THRESHOLD_PX) return
    hasDraggedSincePointerDown.value = true
    isDragging.value = true
  }
  const normalized = clampRootPosition(dragStartLeft.value + deltaX, dragStartTop.value + deltaY)
  rootLeft.value = normalized.left
  rootTop.value = normalized.top
}

const onDragEnd = (event: PointerEvent) => {
  const target = event.currentTarget as HTMLElement | null
  if (target) {
    target.removeEventListener('pointermove', onDragMove)
    target.removeEventListener('pointerup', onDragEnd)
    target.removeEventListener('pointercancel', onDragEnd)
    if (dragPointerId.value !== null && target.hasPointerCapture(dragPointerId.value)) {
      target.releasePointerCapture(dragPointerId.value)
    }
  }
  if (hasDraggedSincePointerDown.value) {
    suppressNextToggleClick.value = true
  }
  dragPointerId.value = null
  isDragging.value = false
  hasDraggedSincePointerDown.value = false
}

const submitMessage = async () => {
  const text = draft.value.trim()
  if (!text || isLoading.value) return
  draft.value = ''
  await sendMessage(text)
  await scrollToBottom()
}

watch(
  () => messages.value.length,
  () => {
    if (isOpen.value) void scrollToBottom()
  },
)

watch(
  () => props.visible,
  (visibleNow) => {
    if (visibleNow) void placeRootToBottomRight()
  },
)

watch(isOpen, (openNow) => {
  if (openNow) void ensurePanelInViewport()
  else keepRootInViewport()
})

watch(callOpen, (active) => {
  voiceCallActive.value = active
  if (active) {
    expandPanelOnCall.value = props.expandCallPanel
    syncCallPanelVisibility()
  }
})

watch(
  () => props.expandCallPanel,
  () => {
    if (!callOpen.value) return
    expandPanelOnCall.value = props.expandCallPanel
    syncCallPanelVisibility()
  },
)

onMounted(() => {
  void placeRootToBottomRight()
  window.addEventListener('resize', onWindowResize)
  window.addEventListener('xcagi:close-floating-chat', closeFloatingChatPanel)
  window.addEventListener('xcagi:close-assistant-float', closeFloatingChatPanel)
  window.addEventListener('xcagi:suppress-floating-chat', suppressFloatingChatPanel)
  window.addEventListener('xcagi:restore-floating-chat', restoreFloatingChatPanel)
  window.addEventListener('xcagi:start-voice-call', onStartVoiceCallRequest)
})

onBeforeUnmount(() => {
  hangUpVoiceCall()
  voiceCallActive.value = false
  window.removeEventListener('resize', onWindowResize)
  window.removeEventListener('xcagi:close-floating-chat', closeFloatingChatPanel)
  window.removeEventListener('xcagi:close-assistant-float', closeFloatingChatPanel)
  window.removeEventListener('xcagi:suppress-floating-chat', suppressFloatingChatPanel)
  window.removeEventListener('xcagi:restore-floating-chat', restoreFloatingChatPanel)
  window.removeEventListener('xcagi:start-voice-call', onStartVoiceCallRequest)
})
</script>

<style scoped src="./FloatingChatAssistant.css"></style>
