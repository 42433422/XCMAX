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
        <button class="floating-chat-close" type="button" aria-label="关闭" @click="isOpen = false">×</button>
      </div>

      <div ref="messageListRef" class="floating-chat-messages">
        <div v-for="(msg, idx) in visibleMessages" :key="`${idx}-${msg.time}`" class="floating-chat-message" :class="msg.role">
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
        <button class="floating-chat-send" type="submit" :disabled="!draft || isLoading">发送</button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useChatView } from '@/composables/useChatView'
import { publicAssetUrl } from '@/utils/publicAssetUrl'
import { sanitizeChatBubbleHtml } from '@/utils/sanitizeHtml'
import { readAiSessionIdFromStorage, writeAiSessionIdToStorage } from '@/utils/xcagiStorageKeys'

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

const visibleMessages = computed(() => messages.value.slice(-20))
const rootStyle = computed(() => ({
  left: `${rootLeft.value}px`,
  top: `${rootTop.value}px`,
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
  },
)

watch(
  () => props.visible,
  (visibleNow) => {
    if (visibleNow) void placeRootToBottomRight()
  },
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

<style scoped src="./FloatingChatAssistant.css"></style>
