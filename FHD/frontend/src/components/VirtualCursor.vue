<template>
  <div
    v-show="visible"
    ref="rootRef"
    class="virtual-cursor-root"
    :class="{ clicking: clicking }"
    :style="rootStyle"
    aria-hidden="true"
  >
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" class="virtual-cursor-svg">
      <path
        d="M5 3 L19 12 L12.5 13.5 L9 20 Z"
        fill="white"
        stroke="black"
        stroke-width="1.5"
        stroke-linejoin="round"
      />
    </svg>
    <span v-if="label" class="virtual-cursor-label">{{ label }}</span>
    <span v-if="clicking" class="virtual-cursor-ripple" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type {
  VirtualCursorApi,
  VirtualCursorClickOptions,
  VirtualCursorMoveOptions,
} from '@/tutorial/virtualCursor.types'

const visible = ref(false)
const x = ref(-9999)
const y = ref(-9999)
const duration = ref(500)
const label = ref('')
const clicking = ref(false)
const rootRef = ref<HTMLElement | null>(null)

let clickTimer: ReturnType<typeof setTimeout> | null = null

const rootStyle = computed(() => ({
  transform: `translate(${x.value}px, ${y.value}px)`,
  transitionDuration: `${duration.value}ms`,
  opacity: visible.value ? '1' : '0',
}))

function resolvePoint(target: HTMLElement | { x: number; y: number }) {
  if (target instanceof HTMLElement) {
    try {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' })
    } catch {
      /* ignore */
    }
    const rect = target.getBoundingClientRect()
    return {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    }
  }
  return { x: target.x, y: target.y }
}

function playClickRipple() {
  if (clickTimer) clearTimeout(clickTimer)
  clicking.value = true
  clickTimer = setTimeout(() => {
    clicking.value = false
    clickTimer = null
  }, 280)
}

function moveTo(
  target: HTMLElement | { x: number; y: number },
  options: VirtualCursorMoveOptions = {},
) {
  const dur = options.duration ?? 500
  duration.value = dur
  label.value = options.label ?? ''
  const pt = resolvePoint(target)
  visible.value = true
  requestAnimationFrame(() => {
    x.value = pt.x
    y.value = pt.y
  })
  if (options.click) {
    window.setTimeout(() => playClickRipple(), dur)
  }
}

function click(target: HTMLElement, options: VirtualCursorClickOptions = {}) {
  const dur = options.duration ?? 500
  moveTo(target, { duration: dur, label: options.label, click: true })
}

function hide() {
  visible.value = false
  label.value = ''
  clicking.value = false
  x.value = -9999
  y.value = -9999
}

function show() {
  visible.value = true
  duration.value = 0
  x.value = window.innerWidth / 2
  y.value = window.innerHeight / 2
}

const api: VirtualCursorApi = { moveTo, click, hide, show }

onMounted(() => {
  window.virtualCursor = api
})

onBeforeUnmount(() => {
  if (clickTimer) clearTimeout(clickTimer)
  delete window.virtualCursor
})
</script>

<style scoped>
.virtual-cursor-root {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 2147483647;
  pointer-events: none;
  transition-property: transform, opacity;
  transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1);
  will-change: transform;
}

.virtual-cursor-svg {
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.5));
  transform: translate(-4px, -2px);
}

.virtual-cursor-label {
  position: absolute;
  top: 32px;
  left: 20px;
  max-width: 220px;
  padding: 6px 10px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.92);
  color: #fff;
  font-size: 12px;
  line-height: 1.35;
  white-space: nowrap;
  animation: vc-label-in 0.22s ease-out;
}

.virtual-cursor-ripple {
  position: absolute;
  top: 0;
  left: 0;
  width: 28px;
  height: 28px;
  margin: -14px 0 0 -14px;
  border-radius: 50%;
  border: 2px solid rgba(59, 130, 246, 0.85);
  animation: vc-ripple 0.28s ease-out forwards;
}

.virtual-cursor-root.clicking .virtual-cursor-svg {
  transform: translate(-4px, -2px) scale(0.94);
}

@keyframes vc-ripple {
  from {
    transform: scale(0.4);
    opacity: 1;
  }
  to {
    transform: scale(2.2);
    opacity: 0;
  }
}

@keyframes vc-label-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
