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
        :width="props.corpMode ? 46 : 38"
        :height="props.corpMode ? 46 : 38"
        decoding="async"
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
  /** 管理端使用男版；官网与客户端统一使用女版小 C。 */
  maleAvatar?: boolean
}>()

const avatarFileName = computed(() =>
  props.maleAvatar ? 'ai-butler-male-avatar-v1.jpg' : 'ai-butler-female-avatar-v1.png',
)

/** 官网与客户端使用女版小 C；管理端明确使用男版。 */
const brandLogoUrl = computed(() =>
  props.corpMode
    ? '/corp-butler/ai-butler-female-avatar-v1.png'
    : `${import.meta.env.BASE_URL}${avatarFileName.value}`,
)

const ballRef = ref<HTMLButtonElement | null>(null)

const DRAG_THRESHOLD_PX = 6
const BALL_WIDTH_ESTIMATE = 132
const CORP_BALL_WIDTH_ESTIMATE = 146
const BALL_HEIGHT_ESTIMATE = 56
const CORP_BALL_HEIGHT_ESTIMATE = 64
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
/* 默认深色；浅色工作台加 .butler-ball--light（与「智能对话」胶囊一致） */
.butler-ball {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 11000;
  pointer-events: auto;
  touch-action: manipulation;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 54px;
  max-width: calc(100vw - 32px);
  padding: 8px 14px 8px 9px;
  margin: 0;
  border: 1px solid color-mix(in srgb, var(--wb-accent-primary, #818cf8) 34%, transparent);
  border-radius: 999px;
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--wb-surface-elevated, #12121a) 94%, transparent) 0%,
    color-mix(in srgb, var(--wb-dialog-bg, #0c0c12) 98%, transparent) 100%
  );
  color: var(--wb-text-primary, #f0f0f5);
  box-shadow:
    0 14px 36px rgba(0, 0, 0, 0.45),
    var(--wb-glow-accent, 0 4px 14px rgba(99, 102, 241, 0.12)),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
  cursor: grab;
  touch-action: none;
  backdrop-filter: blur(12px);
  transition:
    transform 180ms ease,
    box-shadow 180ms ease,
    border-color 180ms ease,
    background 180ms ease,
    opacity 180ms ease;
}

.butler-ball:active {
  cursor: grabbing;
}

.butler-ball:hover {
  border-color: color-mix(in srgb, var(--wb-accent-primary, #818cf8) 52%, transparent);
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--wb-card-hover-bg, rgba(240, 240, 245, 0.06)) 96%, #12121a) 0%,
    color-mix(in srgb, var(--wb-dialog-bg, #0c0c12) 99%, transparent) 100%
  );
  box-shadow:
    0 18px 40px rgba(0, 0, 0, 0.5),
    var(--wb-glow-accent-strong, 0 6px 18px rgba(99, 102, 241, 0.18)),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.butler-ball:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--wb-accent-primary, #818cf8) 42%, transparent);
  outline-offset: 2px;
}

.butler-ball--open {
  z-index: 11020;
  border-color: color-mix(in srgb, var(--wb-accent-primary, #818cf8) 58%, transparent);
  box-shadow:
    0 18px 40px rgba(0, 0, 0, 0.52),
    var(--wb-glow-accent-strong, 0 0 24px rgba(99, 102, 241, 0.2)),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
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
  width: 38px;
  height: 38px;
  border-radius: 50%;
  display: inline-grid;
  place-items: center;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid color-mix(in srgb, var(--wb-accent-primary, #818cf8) 36%, transparent);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.28);
  flex: 0 0 auto;
}

.butler-ball__logo {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: 50% 37%;
  transform: scale(1.08);
  display: block;
}

.butler-ball__label {
  font-size: 14px;
  line-height: 1;
  font-weight: 800;
  letter-spacing: 0.01em;
  white-space: nowrap;
  color: var(--wb-text-primary, #f0f0f5);
  flex: 0 1 auto;
}

.butler-ball__badge {
  position: absolute;
  top: -4px;
  right: 6px;
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
  border-color: color-mix(in srgb, var(--wb-accent-primary, #0071e3) 34%, transparent);
  background: linear-gradient(
    180deg,
    var(--wb-surface-elevated, rgba(255, 255, 255, 0.96)),
    color-mix(in srgb, var(--wb-accent-soft, rgba(0, 113, 227, 0.1)) 80%, #fff)
  );
  color: var(--wb-text-primary, #1d1d1f);
  box-shadow: var(--wb-card-shadow, 0 14px 30px rgba(0, 0, 0, 0.08));
  backdrop-filter: none;
}

.butler-ball.butler-ball--light:hover {
  border-color: color-mix(in srgb, var(--wb-accent-primary, #0071e3) 52%, transparent);
  background: linear-gradient(
    180deg,
    #fff,
    color-mix(in srgb, var(--wb-accent-soft, rgba(0, 113, 227, 0.12)) 70%, #fff)
  );
  box-shadow: var(--wb-card-shadow, 0 18px 36px rgba(0, 0, 0, 0.1));
}

.butler-ball.butler-ball--light.butler-ball--open {
  border-color: color-mix(in srgb, var(--wb-accent-primary, #0071e3) 58%, transparent);
  background: linear-gradient(
    180deg,
    #fff,
    color-mix(in srgb, var(--wb-accent-soft, rgba(0, 113, 227, 0.14)) 75%, #fff)
  );
}

.butler-ball.butler-ball--light .butler-ball__logo-wrap {
  background: rgba(255, 255, 255, 0.88);
  border-color: color-mix(in srgb, var(--wb-accent-primary, #0071e3) 38%, transparent);
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.08);
}

.butler-ball.butler-ball--light .butler-ball__label {
  color: var(--wb-text-primary, #1d1d1f);
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

/* 官网：默认 top/left 0，实际位置由 transform + xc_butler_pos_corp 决定，可拖动 */
.butler-ball.butler-ball--corp-anchor {
  top: 0;
  left: 0;
  right: auto;
  bottom: auto;
  cursor: grab;
  touch-action: none;
  /* 面板打开时仍须高于 .butler-panel(20002)，否则拖不动 */
  z-index: 20005;
  min-width: 146px;
  min-height: 64px;
  height: 64px;
  gap: 9px;
  padding: 7px 16px 7px 8px;
  border-color: rgba(119, 112, 255, 0.52);
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(242, 246, 255, 0.98)),
    linear-gradient(135deg, #796fff, #44b9ff);
  box-shadow:
    0 14px 30px rgba(28, 78, 148, 0.18),
    0 0 0 4px rgba(130, 115, 255, 0.1);
}

.butler-ball.butler-ball--corp-anchor .butler-ball__label {
  display: inline;
  color: #20274a;
  letter-spacing: 0.025em;
}

.butler-ball.butler-ball--corp-anchor .butler-ball__logo-wrap {
  width: 48px;
  height: 48px;
  border: 2px solid rgba(255, 255, 255, 0.96);
  box-shadow:
    0 0 0 2px rgba(119, 112, 255, 0.58),
    0 5px 12px rgba(83, 102, 209, 0.25);
}

.butler-ball.butler-ball--corp-anchor:hover {
  border-color: rgba(104, 98, 245, 0.8);
  background: linear-gradient(135deg, #fff, #edf5ff);
  box-shadow:
    0 18px 36px rgba(28, 78, 148, 0.24),
    0 0 0 5px rgba(130, 115, 255, 0.13);
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
