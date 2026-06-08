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
    }"
    :style="ballStyle"
    :aria-label="consentGiven ? (isOpen ? '关闭 AI 管家' : '打开 AI 管家') : '启用 AI 数字管家'"
    :title="consentGiven ? (props.corpMode ? '拖动可移动；点击打开/关闭' : 'AI 管家') : '启用 AI 管家'"
    @click.stop="handleClick"
    @pointerdown="onPointerDown"
  >
    <span class="butler-ball__logo-wrap" aria-hidden="true">
      <img
        class="butler-ball__logo"
        :src="brandLogoUrl"
        alt=""
        width="34"
        height="34"
        decoding="async"
      />
    </span>
    <span class="butler-ball__label">AI 管家</span>
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

const props = defineProps<{ isSpeaking?: boolean; forceLight?: boolean; corpMode?: boolean }>()

/** 与 FHD「智能对话」悬浮钮同款品牌标 */
const brandLogoUrl = computed(() =>
  props.forceLight ? '/corp-butler/brand-xc-logo.jpg' : `${import.meta.env.BASE_URL}brand-xc-logo.jpg`,
)

const ballRef = ref<HTMLButtonElement | null>(null)

const DRAG_THRESHOLD_PX = 6
const BALL_WIDTH_ESTIMATE = 132
const BALL_HEIGHT_ESTIMATE = 56
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
  const maxX = window.innerWidth - BALL_WIDTH_ESTIMATE - 8
  const maxY = window.innerHeight - BALL_HEIGHT_ESTIMATE - 8
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
  border: 1px solid rgba(96, 165, 250, 0.32);
  border-radius: 999px;
  background: linear-gradient(
    180deg,
    rgba(30, 41, 59, 0.94) 0%,
    rgba(15, 23, 42, 0.98) 100%
  );
  color: var(--wb-text-primary, #e2e8f0);
  box-shadow:
    0 14px 36px rgba(0, 0, 0, 0.45),
    0 4px 14px rgba(56, 189, 248, 0.12),
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
  border-color: rgba(125, 211, 252, 0.55);
  background: linear-gradient(
    180deg,
    rgba(38, 52, 72, 0.96) 0%,
    rgba(20, 30, 48, 0.99) 100%
  );
  box-shadow:
    0 18px 40px rgba(0, 0, 0, 0.5),
    0 6px 18px rgba(56, 189, 248, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.butler-ball:focus-visible {
  outline: 3px solid rgba(56, 189, 248, 0.38);
  outline-offset: 2px;
}

.butler-ball--open {
  z-index: 11020;
  border-color: rgba(125, 211, 252, 0.62);
  box-shadow:
    0 18px 40px rgba(0, 0, 0, 0.52),
    0 0 24px rgba(56, 189, 248, 0.2),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.butler-ball--consent-pending {
  opacity: 0.82;
}

.butler-ball__logo-wrap {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: inline-grid;
  place-items: center;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(125, 211, 252, 0.35);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.28);
  flex: 0 0 auto;
}

.butler-ball__logo {
  width: 34px;
  height: 34px;
  object-fit: contain;
  display: block;
}

.butler-ball__label {
  font-size: 14px;
  line-height: 1;
  font-weight: 800;
  letter-spacing: 0.01em;
  white-space: nowrap;
  color: #e0f2fe;
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
  color: #bae6fd;
  white-space: nowrap;
  pointer-events: none;
  background: rgba(15, 23, 42, 0.92);
  border: 1px solid rgba(96, 165, 250, 0.35);
  padding: 3px 8px;
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
}

.butler-ball.butler-ball--light {
  border-color: rgba(74, 144, 217, 0.36);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(239, 246, 255, 0.94));
  color: #172033;
  box-shadow:
    0 14px 30px rgba(15, 76, 129, 0.18),
    0 4px 12px rgba(37, 99, 235, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.92);
  backdrop-filter: none;
}

.butler-ball.butler-ball--light:hover {
  border-color: rgba(37, 99, 235, 0.58);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.99), rgba(219, 234, 254, 0.96));
  box-shadow:
    0 18px 36px rgba(15, 76, 129, 0.22),
    0 6px 16px rgba(37, 99, 235, 0.16),
    inset 0 1px 0 rgba(255, 255, 255, 0.96);
}

.butler-ball.butler-ball--light.butler-ball--open {
  border-color: rgba(37, 99, 235, 0.62);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.99), rgba(219, 234, 254, 0.98));
}

.butler-ball.butler-ball--light .butler-ball__logo-wrap {
  background: rgba(255, 255, 255, 0.88);
  border-color: rgba(24, 144, 255, 0.42);
  box-shadow: 0 4px 10px rgba(15, 76, 129, 0.12);
}

.butler-ball.butler-ball--light .butler-ball__label {
  color: #1e3a8a;
}

.butler-ball.butler-ball--light .butler-ball__badge {
  box-shadow: 0 0 0 2px #fff;
}

.butler-ball.butler-ball--light .butler-ball__hint {
  color: #1e3a8a;
  background: rgba(255, 255, 255, 0.95);
  border-color: rgba(74, 144, 217, 0.35);
  box-shadow: 0 4px 12px rgba(15, 76, 129, 0.12);
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
