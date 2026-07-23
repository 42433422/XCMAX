<template>
  <button
    ref="ballRef"
    type="button"
    class="butler-ball"
    :class="{
      'butler-ball--light': forceLight || isLightTheme,
      'butler-ball--consent-pending': !consentGiven,
      'butler-ball--open': isOpen,
      'butler-ball--corp-anchor': props.corpMode,
      'butler-ball--dragging': isDraggingUi,
      'butler-ball--speaking': !!props.isSpeaking,
    }"
    :style="ballStyle"
    aria-label="小C助理"
    title="小C助理"
    @click.stop="handleClick"
    @pointerdown="onPointerDown"
  >
    <span class="butler-ball__logo-wrap" aria-hidden="true">
      <img
        class="butler-ball__logo"
        :src="brandLogoUrl"
        alt=""
        :width="56"
        :height="56"
        decoding="async"
        draggable="false"
        @dragstart.prevent
      />
    </span>
    <span class="butler-ball__label">小C助理</span>
    <span
      v-if="fileOverflowCount > 0 && !isOpen"
      class="butler-ball__badge butler-ball__badge--files"
      :title="`${fileOverflowCount} 个文件已收纳`"
    >
      {{ fileOverflowCount > 9 ? '9+' : fileOverflowCount }}
    </span>
    <span
      v-else-if="unreadCount > 0 && !isOpen"
      class="butler-ball__badge"
    >
      {{ unreadCount > 9 ? '9+' : unreadCount }}
    </span>
    <span v-if="!consentGiven" class="butler-ball__hint">点我启用</span>
  </button>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from 'vue'
import { storeToRefs } from 'pinia'
import { useAgentStore } from '../../stores/agent'
import { useButlerWorkbenchTrayStore } from '../../stores/butlerWorkbenchTray'
import { useWorkbenchTheme } from '../../composables/useWorkbenchTheme'
import { saveCorpBallPosition } from '../../corp-butler/corpBallPosition'

const agentStore = useAgentStore()
const trayStore = useButlerWorkbenchTrayStore()
const { isOpen, consentGiven, unreadCount, position } = storeToRefs(agentStore)
const { overflowCount: fileOverflowCount } = storeToRefs(trayStore)

const props = defineProps<{
  isSpeaking?: boolean
  forceLight?: boolean
  corpMode?: boolean
  /** 管理员账号使用男版；普通用户与官网统一女版小 C。 */
  maleAvatar?: boolean
}>()

const avatarFileName = computed(() =>
  props.maleAvatar ? 'ai-butler-male-avatar-v1.jpg' : 'ai-butler-female-avatar-v1.png',
)

/** 官网固定女版；市场内按 maleAvatar 切换管理员男版 / 普通女版。 */
const brandLogoUrl = computed(() =>
  props.corpMode
    ? '/corp-butler/ai-butler-female-avatar-v1.png'
    : `${import.meta.env.BASE_URL}${avatarFileName.value}`,
)

const ballRef = ref<HTMLButtonElement | null>(null)

const DRAG_THRESHOLD_PX = 6
/** 竖排：头像上 + 名称下（非胶囊） */
const BALL_WIDTH_ESTIMATE = 72
const CORP_BALL_WIDTH_ESTIMATE = 72
const BALL_HEIGHT_ESTIMATE = 88
const CORP_BALL_HEIGHT_ESTIMATE = 88
let isDragging = false
let dragStartX = 0
let dragStartY = 0
let pointerStartX = 0
let pointerStartY = 0
/** 本次按下是否发生过拖动（在 click 前保持，避免拖完误触开关） */
let suppressClickAfterDrag = false
const isDraggingUi = ref(false)

const pos = computed(() => position.value ?? { x: 0, y: 0 })
const ballStyle = computed(() => ({
  transform: `translate(${pos.value.x}px, ${pos.value.y}px)`,
}))
const { isLightTheme } = useWorkbenchTheme()
const forceLight = computed(() => !!props.forceLight)

function onPointerDown(e: PointerEvent) {
  if (e.button !== 0) return
  isDragging = true
  suppressClickAfterDrag = false
  pointerStartX = e.clientX
  pointerStartY = e.clientY
  dragStartX = e.clientX - pos.value.x
  dragStartY = e.clientY - pos.value.y
  ballRef.value?.setPointerCapture(e.pointerId)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
}

function onPointerMove(e: PointerEvent) {
  if (!isDragging) return
  const dx = e.clientX - pointerStartX
  const dy = e.clientY - pointerStartY
  if (Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return
  suppressClickAfterDrag = true
  isDraggingUi.value = true
  const nx = e.clientX - dragStartX
  const ny = e.clientY - dragStartY
  const ballWidth = props.corpMode ? CORP_BALL_WIDTH_ESTIMATE : BALL_WIDTH_ESTIMATE
  const ballHeight = props.corpMode ? CORP_BALL_HEIGHT_ESTIMATE : BALL_HEIGHT_ESTIMATE
  const maxX = window.innerWidth - ballWidth - 8
  const maxY = window.innerHeight - ballHeight - 8
  const x = Math.max(8, Math.min(maxX, nx))
  const y = Math.max(8, Math.min(maxY, ny))
  if (props.corpMode) {
    const p = saveCorpBallPosition(x, y)
    agentStore.savePosition(p.x, p.y)
    return
  }
  agentStore.savePosition(x, y)
}

function onPointerUp(e: PointerEvent) {
  isDragging = false
  isDraggingUi.value = false
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  try {
    ballRef.value?.releasePointerCapture(e.pointerId)
  } catch {
    // ignore
  }
  // 开关只由 click 处理，避免 pointerup + click 连触导致「开了又立刻关」
}

function handleToggle() {
  if (!agentStore.consentGiven) {
    agentStore.showPermissionDialog = true
    return
  }
  if (agentStore.isOpen) {
    agentStore.closePanel()
  } else {
    agentStore.openPanel()
  }
}

function handleClick() {
  if (suppressClickAfterDrag) {
    suppressClickAfterDrag = false
    return
  }
  handleToggle()
}

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
})
</script>

<style scoped>
/* 竖排固定格式：圆形头像居中上 + 底部名称；无胶囊底栏 */
.butler-ball {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 11000;
  pointer-events: auto;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  width: 72px;
  min-width: 72px;
  min-height: 88px;
  max-width: calc(100vw - 32px);
  padding: 0;
  margin: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--wb-text-primary, #f0f0f5);
  box-shadow: none;
  cursor: grab;
  touch-action: none;
  backdrop-filter: none;
  user-select: none;
  -webkit-user-select: none;
  transition:
    transform 180ms ease,
    opacity 180ms ease;
}

.butler-ball:active {
  cursor: grabbing;
}

.butler-ball:hover .butler-ball__logo-wrap {
  transform: translateY(-1px);
  box-shadow: 0 8px 18px rgba(0, 0, 0, 0.32);
}

.butler-ball:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--wb-accent-primary, #818cf8) 42%, transparent);
  outline-offset: 4px;
  border-radius: 16px;
}

.butler-ball--open {
  z-index: 11020;
}

.butler-ball--consent-pending {
  opacity: 0.82;
}

.butler-ball--speaking .butler-ball__logo-wrap {
  animation: butler-speak-pulse 1.1s ease-in-out infinite;
}

@keyframes butler-speak-pulse {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.07);
  }
}

.butler-ball__logo-wrap {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: inline-grid;
  place-items: center;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid color-mix(in srgb, var(--wb-accent-primary, #818cf8) 36%, transparent);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.28);
  flex: 0 0 auto;
  transition: transform 180ms ease, box-shadow 180ms ease;
  user-select: none;
  -webkit-user-drag: none;
}

.butler-ball__logo {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: 50% 37%;
  transform: scale(1.08);
  display: block;
  pointer-events: none;
  user-select: none;
  -webkit-user-drag: none;
}

.butler-ball__label {
  font-size: 12px;
  line-height: 1.15;
  font-weight: 800;
  letter-spacing: 0.01em;
  white-space: nowrap;
  color: var(--wb-text-primary, #f0f0f5);
  flex: 0 0 auto;
  text-align: center;
  text-shadow:
    0 1px 0 rgba(0, 0, 0, 0.35),
    0 0 8px rgba(0, 0, 0, 0.25);
}

.butler-ball__badge {
  position: absolute;
  top: 4px;
  right: 4px;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  border-radius: 999px;
  background: linear-gradient(180deg, #fb7185, #ef4444);
  color: #fff;
  font-size: 0.65rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 0 0 2px #0f172a;
  pointer-events: none;
}

.butler-ball__badge--files {
  background: linear-gradient(180deg, #a5b4fc, #6366f1);
  box-shadow: 0 0 0 2px #0f172a;
}

.butler-ball__hint {
  position: absolute;
  bottom: -26px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 0.65rem;
  color: var(--wb-text-secondary, rgba(240, 240, 245, 0.82));
  white-space: nowrap;
  pointer-events: none;
  background: color-mix(in srgb, var(--wb-dialog-bg, #0c0c12) 92%, transparent);
  border: 1px solid color-mix(in srgb, var(--wb-accent-primary, #818cf8) 32%, transparent);
  padding: 3px 8px;
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
}

.butler-ball.butler-ball--light {
  background: transparent;
  border: 0;
  box-shadow: none;
  color: var(--wb-text-primary, #1d1d1f);
}

.butler-ball.butler-ball--light .butler-ball__logo-wrap {
  background: rgba(255, 255, 255, 0.96);
  border-color: color-mix(in srgb, var(--wb-accent-primary, #0071e3) 38%, transparent);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.12);
}

.butler-ball.butler-ball--light .butler-ball__label {
  color: var(--wb-text-primary, #1d1d1f);
  text-shadow:
    0 1px 0 rgba(255, 255, 255, 0.9),
    0 0 8px rgba(255, 255, 255, 0.55);
}

.butler-ball.butler-ball--light .butler-ball__badge {
  box-shadow: 0 0 0 2px #fff;
}

.butler-ball.butler-ball--light .butler-ball__hint {
  color: var(--wb-accent-primary, #0071e3);
  background: rgba(255, 255, 255, 0.95);
  border-color: color-mix(in srgb, var(--wb-accent-primary, #0071e3) 32%, transparent);
  box-shadow: var(--wb-card-shadow, 0 4px 12px rgba(0, 0, 0, 0.08));
}

/* 官网：与市场同为竖排头像+名称（无胶囊底） */
.butler-ball.butler-ball--corp-anchor {
  top: 0;
  left: 0;
  right: auto;
  bottom: auto;
  cursor: grab;
  touch-action: none;
  /* 面板打开时仍须高于 .butler-panel(20002)，否则拖不动 */
  z-index: 20005;
  width: 72px;
  min-width: 72px;
  min-height: 88px;
  height: auto;
  gap: 6px;
  padding: 0;
  border: 0;
  background: transparent;
  box-shadow: none;
}

.butler-ball.butler-ball--corp-anchor .butler-ball__label {
  display: block;
  color: #20274a;
  letter-spacing: 0.025em;
  text-shadow:
    0 1px 0 rgba(255, 255, 255, 0.95),
    0 0 8px rgba(255, 255, 255, 0.6);
}

.butler-ball.butler-ball--corp-anchor .butler-ball__logo-wrap {
  width: 56px;
  height: 56px;
  border: 2px solid rgba(255, 255, 255, 0.96);
  box-shadow:
    0 0 0 2px rgba(119, 112, 255, 0.58),
    0 5px 12px rgba(83, 102, 209, 0.25);
}

.butler-ball.butler-ball--corp-anchor:hover {
  background: transparent;
  box-shadow: none;
}

.butler-ball.butler-ball--corp-anchor.butler-ball--open {
  z-index: 20005;
}

.butler-ball.butler-ball--corp-anchor.butler-ball--dragging {
  transition: none;
  z-index: 20006;
}

.butler-ball.butler-ball--corp-anchor:active {
  cursor: grabbing;
}
</style>
