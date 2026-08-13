<template>
  <div
    v-if="props.visible && !externallyHidden"
    ref="rootRef"
    class="floating-chat-root"
    :class="{ dragging: isDragging }"
    :style="rootStyle"
  >
    <button
      class="floating-chat-toggle"
      :class="{ 'floating-chat-toggle--admin': props.maleAvatar }"
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
      <span class="floating-chat-toggle-label">小C助理</span>
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
          <div id="floating-chat-title" class="floating-chat-title">小C助理</div>
        </div>
        <button class="floating-chat-close" type="button" aria-label="关闭" @click="isOpen = false">
          ×
        </button>
      </div>

      <div ref="messageListRef" class="floating-chat-messages">
        <div
          v-for="(msg, idx) in visibleMessages"
          :key="`${idx}-${msg.time}`"
          class="floating-chat-message"
          :class="msg.role"
        >
          <div class="floating-chat-bubble" v-html="sanitizeChatBubbleHtml(msg.content)"></div>
          <div class="floating-chat-time">{{ msg.time }}</div>
        </div>
        <div v-if="isLoading && !isStreamingReply" class="floating-chat-message ai">
          <div class="floating-chat-bubble">{{ loadingProgressText }}</div>
        </div>
      </div>

      <form class="floating-chat-input-row" @submit.prevent="submitMessage">
        <textarea
          v-model.trim="draft"
          class="floating-chat-input"
          rows="2"
          placeholder="输入消息..."
          :disabled="isLoading"
          @keydown.enter.exact.prevent="submitMessage"
        ></textarea>
        <button class="floating-chat-send" type="submit" :disabled="!draft || isLoading">
          发送
        </button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useChatView } from '@/composables/useChatView'
import { sanitizeChatBubbleHtml } from '@/utils/sanitizeHtml'
import { readAiSessionIdFromStorage, writeAiSessionIdToStorage } from '@/utils/xcagiStorageKeys'

const props = defineProps({
  visible: {
    type: Boolean,
    default: true
  },
  /** 管理端（含其登录入口）使用男版；桌面端和客户端使用女版。 */
  maleAvatar: {
    type: Boolean,
    default: false
  }
})

const avatarUrl = computed(() =>
  props.maleAvatar ? '/ai-butler-male-avatar-v1.jpg' : '/ai-butler-female-avatar-v1.png',
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
const dragPointerId = ref<number | null>(null)
const dragStartClientX = ref(0)
const dragStartClientY = ref(0)
const dragStartLeft = ref(0)
const dragStartTop = ref(0)
const DRAG_THRESHOLD_PX = 4
const EDGE_PADDING_PX = 8
const ROOT_MARGIN_PX = 22

const {
  messages,
  isLoading,
  isStreamingReply,
  loadingProgressText,
  sendMessage,
} = useChatView({
  sessionId: currentSessionId,
})

const visibleMessages = computed(() => messages.value.slice(-20))
const rootStyle = computed(() => ({
  left: `${rootLeft.value}px`,
  top: `${rootTop.value}px`
}))

const closeFloatingChatPanel = () => {
  isOpen.value = false
}

const suppressFloatingChatPanel = () => {
  isOpen.value = false
  externallyHidden.value = true
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

const scrollToBottom = async () => {
  await nextTick()
  const el = messageListRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

const toggleOpen = async () => {
  if (suppressNextToggleClick.value) {
    suppressNextToggleClick.value = false
    return
  }
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
  }
)

watch(
  () => props.visible,
  (visibleNow) => {
    if (visibleNow) void placeRootToBottomRight()
  }
)

watch(isOpen, () => {
  void nextTick(() => {
    keepRootInViewport()
  })
})

onMounted(() => {
  void placeRootToBottomRight()
  window.addEventListener('resize', keepRootInViewport)
  window.addEventListener('xcagi:close-floating-chat', closeFloatingChatPanel)
  window.addEventListener('xcagi:close-assistant-float', closeFloatingChatPanel)
  window.addEventListener('xcagi:suppress-floating-chat', suppressFloatingChatPanel)
  window.addEventListener('xcagi:restore-floating-chat', restoreFloatingChatPanel)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', keepRootInViewport)
  window.removeEventListener('xcagi:close-floating-chat', closeFloatingChatPanel)
  window.removeEventListener('xcagi:close-assistant-float', closeFloatingChatPanel)
  window.removeEventListener('xcagi:suppress-floating-chat', suppressFloatingChatPanel)
  window.removeEventListener('xcagi:restore-floating-chat', restoreFloatingChatPanel)
})
</script>

<style scoped>
.floating-chat-root {
  position: fixed;
  max-width: calc(100vw - 16px);
  max-height: calc(100vh - 16px);
  z-index: 2600;
}

.floating-chat-root.dragging {
  user-select: none;
}

.floating-chat-toggle {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  width: 64px;
  min-height: 82px;
  max-width: calc(100vw - 32px);
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: #172033;
  box-shadow: none;
  transition:
    transform 180ms ease,
    box-shadow 180ms ease,
    border-color 180ms ease,
    background 180ms ease;
  touch-action: none;
}

.floating-chat-toggle-avatar {
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  width: 56px;
  height: 56px;
  overflow: hidden;
  border: 2px solid rgba(255, 255, 255, 0.96);
  border-radius: 50%;
  background: #e9edff;
  box-shadow:
    0 0 0 2px rgba(95, 112, 237, 0.54),
    0 5px 12px rgba(60, 95, 185, 0.22);
}

.floating-chat-toggle-avatar img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: 50% 37%;
  transform: scale(1.08);
  user-select: none;
  -webkit-user-drag: none;
  pointer-events: none;
}

.floating-chat-toggle--admin .floating-chat-toggle-avatar {
  box-shadow:
    0 0 0 2px rgba(45, 122, 220, 0.58),
    0 5px 12px rgba(22, 77, 143, 0.25);
}

.floating-chat-root:not(.dragging) .floating-chat-toggle {
  cursor: grab;
}

.floating-chat-root.dragging .floating-chat-toggle {
  cursor: grabbing;
}

.floating-chat-toggle:hover {
  background: transparent;
}

.floating-chat-toggle:hover .floating-chat-toggle-avatar {
  border-color: rgba(255, 255, 255, 1);
  box-shadow:
    0 0 0 3px rgba(37, 99, 235, 0.24),
    0 8px 18px rgba(37, 99, 235, 0.22);
}

.floating-chat-toggle:focus-visible,
.floating-chat-close:focus-visible,
.floating-chat-send:focus-visible,
.floating-chat-input:focus-visible {
  outline: 3px solid rgba(24, 144, 255, 0.32);
  outline-offset: 2px;
  border-radius: 10px;
}

.floating-chat-toggle-label {
  font-size: 13px;
  line-height: 16px;
  font-weight: 600;
  letter-spacing: 0.01em;
  white-space: nowrap;
  color: #1e3a8a;
  text-align: center;
  text-shadow: 0 1px 3px rgba(255, 255, 255, 0.88);
}

.floating-chat-panel {
  position: absolute;
  right: 0;
  bottom: 94px;
  width: min(380px, calc(100vw - 28px));
  height: min(560px, calc(100vh - 110px));
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid rgba(147, 197, 253, 0.55);
  box-shadow:
    0 22px 52px rgba(15, 76, 129, 0.22),
    0 8px 18px rgba(37, 99, 235, 0.12);
}

.floating-chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 12px 10px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.92);
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.98), rgba(255, 255, 255, 0.96));
  cursor: grab;
  touch-action: none;
}

.floating-chat-root.dragging .floating-chat-header {
  cursor: grabbing;
}

.floating-chat-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.floating-chat-title {
  font-size: 14px;
  line-height: 1.2;
  font-weight: 800;
  color: #172033;
}

.floating-chat-close {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: #64748b;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
}

.floating-chat-close:hover {
  background: rgba(219, 234, 254, 0.72);
  color: #1e3a8a;
}

.floating-chat-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
  background:
    radial-gradient(circle at 80% 0%, rgba(219, 234, 254, 0.7), transparent 36%),
    linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
}

.floating-chat-message {
  display: flex;
  flex-direction: column;
  margin-bottom: 10px;
}

.floating-chat-message.user {
  align-items: flex-end;
}

.floating-chat-message.ai,
.floating-chat-message.task {
  align-items: flex-start;
}

.floating-chat-bubble {
  max-width: 86%;
  padding: 9px 11px;
  border-radius: 14px;
  font-size: 13px;
  line-height: 1.55;
  color: #172033;
  background: #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.9);
  box-shadow: 0 4px 12px rgba(15, 76, 129, 0.06);
  overflow-wrap: anywhere;
}

.floating-chat-message.user .floating-chat-bubble {
  color: #ffffff;
  background: linear-gradient(135deg, #2563eb 0%, #1890ff 100%);
  border-color: rgba(37, 99, 235, 0.2);
}

.floating-chat-time {
  margin-top: 3px;
  padding: 0 4px;
  font-size: 10px;
  color: rgba(100, 116, 139, 0.78);
}

.floating-chat-input-row {
  display: flex;
  gap: 8px;
  padding: 10px;
  border-top: 1px solid rgba(226, 232, 240, 0.92);
  background: rgba(255, 255, 255, 0.98);
}

.floating-chat-input {
  flex: 1;
  min-width: 0;
  resize: none;
  border: 1px solid rgba(203, 213, 225, 0.95);
  border-radius: 12px;
  padding: 9px 10px;
  font: inherit;
  font-size: 13px;
  line-height: 1.45;
  color: #172033;
  background: #ffffff;
}

.floating-chat-send {
  align-self: stretch;
  min-width: 58px;
  border: none;
  border-radius: 12px;
  background: #2563eb;
  color: #ffffff;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
}

.floating-chat-send:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

@media (max-width: 767px) {
  .floating-chat-root {
    max-width: calc(100vw - 12px);
  }

  .floating-chat-toggle {
    width: 60px;
    min-height: 78px;
    padding: 0;
  }

  .floating-chat-toggle-avatar {
    width: 52px;
    height: 52px;
  }

  .floating-chat-panel {
    bottom: 90px;
    height: min(520px, calc(100vh - 90px));
  }
}
</style>
