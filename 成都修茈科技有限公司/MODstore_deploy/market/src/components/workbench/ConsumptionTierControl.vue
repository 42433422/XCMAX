<template>
  <div
    class="ctc"
    :class="{ 'ctc--dragging': dragging }"
    role="group"
    aria-labelledby="ctc-lbl"
    aria-describedby="ctc-hint"
  >
    <span id="ctc-hint" class="ctc__sr">{{ hint }}</span>
    <div class="ctc__head">
      <span id="ctc-lbl" class="ctc__label">消费档位（1–10）</span>
      <span class="ctc__current" :style="{ color: currentColor }">
        {{ clamped }}
      </span>
    </div>
    <div
      ref="trackRef"
      class="ctc__track"
      role="slider"
      :aria-valuemin="1"
      :aria-valuemax="10"
      :aria-valuenow="clamped"
      :aria-valuetext="`第 ${clamped} 档`"
      :title="hint"
      tabindex="0"
      @pointerdown="onPointerDown"
      @keydown="onKeydown"
    >
      <span class="ctc__bar" aria-hidden="true" />
      <span class="ctc__steps" aria-hidden="true">
        <span
          v-for="n in 9"
          :key="`s-${n}`"
          class="ctc__step"
          :style="{ left: `${(n / 9) * 100}%` }"
        />
      </span>
      <span
        class="ctc__thumb"
        :style="{ left: thumbLeft, borderColor: currentColor, boxShadow: thumbShadow }"
      >
        <span class="ctc__thumb-num">{{ clamped }}</span>
      </span>
    </div>
    <div class="ctc__ticks" role="presentation">
      <button
        v-for="n in 10"
        :key="n"
        type="button"
        class="ctc__tick"
        :class="{ 'ctc__tick--on': clamped === n }"
        :style="clamped === n ? { color: TIER_COLORS[n - 1] } : null"
        :title="`第 ${n} 档`"
        @click="setTier(n)"
      >
        {{ n }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  modelValue: number
}>()

const emit = defineEmits<{
  'update:modelValue': [value: number]
  change: [value: number]
}>()

const hint = '数值越高效果越好、花费越多；占位控件，后续可依据实时榜单自选'

/** 1→10 的渐变色锚（与轨道 linear-gradient 视觉一致） */
const TIER_COLORS = [
  '#38bdf8',
  '#22d3ee',
  '#10b981',
  '#84cc16',
  '#eab308',
  '#f59e0b',
  '#f97316',
  '#ef4444',
  '#ec4899',
  '#a855f7',
]

function clampTier(v: unknown): number {
  const n = Math.round(Number(v) || 1)
  if (!Number.isFinite(n)) return 1
  return Math.min(10, Math.max(1, n))
}

const trackRef = ref<HTMLElement | null>(null)
const dragging = ref(false)

const clamped = computed(() => clampTier(props.modelValue))
const thumbLeft = computed(() => `${((clamped.value - 1) / 9) * 100}%`)
const currentColor = computed(() => TIER_COLORS[clamped.value - 1])
const thumbShadow = computed(
  () => `0 4px 14px rgba(0, 0, 0, 0.35), 0 0 0 4px ${currentColor.value}26`,
)

function setTier(n: number) {
  const v = clampTier(n)
  if (v !== clamped.value) {
    emit('update:modelValue', v)
    emit('change', v)
  }
}

function valueAtClientX(clientX: number): number {
  const el = trackRef.value
  if (!el) return clamped.value
  const rect = el.getBoundingClientRect()
  if (rect.width <= 0) return clamped.value
  const ratio = (clientX - rect.left) / rect.width
  const exact = 1 + Math.max(0, Math.min(1, ratio)) * 9
  return clampTier(Math.round(exact))
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  setTier(valueAtClientX(e.clientX))
}

function endDrag() {
  if (!dragging.value) return
  dragging.value = false
  trackRef.value?.removeEventListener('pointermove', onPointerMove)
  trackRef.value?.removeEventListener('pointerup', endDrag as EventListener)
  trackRef.value?.removeEventListener('pointercancel', endDrag as EventListener)
}

function onPointerDown(e: PointerEvent) {
  const el = trackRef.value
  if (!el) return
  el.setPointerCapture?.(e.pointerId)
  dragging.value = true
  setTier(valueAtClientX(e.clientX))
  el.addEventListener('pointermove', onPointerMove)
  el.addEventListener('pointerup', endDrag as EventListener, { once: true })
  el.addEventListener('pointercancel', endDrag as EventListener, { once: true })
}

function onKeydown(e: KeyboardEvent) {
  let next = clamped.value
  switch (e.key) {
    case 'ArrowLeft':
    case 'ArrowDown':
      next -= 1
      break
    case 'ArrowRight':
    case 'ArrowUp':
      next += 1
      break
    case 'PageDown':
      next -= 2
      break
    case 'PageUp':
      next += 2
      break
    case 'Home':
      next = 1
      break
    case 'End':
      next = 10
      break
    default:
      return
  }
  e.preventDefault()
  setTier(next)
}
</script>

<style scoped>
.ctc {
  --ctc-thumb-size: 1.55rem;
  --ctc-thumb-gutter: calc(var(--ctc-thumb-size) / 2);

  position: relative;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  width: 100%;
  max-width: 22rem;
  padding-inline: var(--ctc-thumb-gutter);
  user-select: none;
}

.ctc__head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem;
}

.ctc__label {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(148, 163, 184, 0.72);
}

.ctc__current {
  font-size: 0.95rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  transition: color 0.18s ease;
}

.ctc__track {
  position: relative;
  height: 1.6rem;
  cursor: pointer;
  outline: none;
  touch-action: none;
}

.ctc__track:focus-visible {
  outline: 2px solid rgba(129, 140, 248, 0.65);
  outline-offset: 4px;
  border-radius: 999px;
}

.ctc__bar {
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 0.55rem;
  transform: translateY(-50%);
  border-radius: 999px;
  background: linear-gradient(
    to right,
    #38bdf8 0%,
    #22d3ee 11%,
    #10b981 22%,
    #84cc16 33%,
    #eab308 44%,
    #f59e0b 55%,
    #f97316 67%,
    #ef4444 78%,
    #ec4899 89%,
    #a855f7 100%
  );
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.1),
    0 1px 2px rgba(0, 0, 0, 0.32);
}

.ctc__steps {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.ctc__step {
  position: absolute;
  top: 50%;
  width: 1px;
  height: 0.45rem;
  background: rgba(15, 23, 42, 0.55);
  transform: translate(-50%, -50%);
  border-radius: 999px;
}

.ctc__thumb {
  position: absolute;
  top: 50%;
  width: var(--ctc-thumb-size);
  height: var(--ctc-thumb-size);
  display: grid;
  place-items: center;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.96);
  border: 2px solid rgba(255, 255, 255, 0.85);
  color: #f8fafc;
  font-size: 0.7rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  transform: translate(-50%, -50%);
  transition: left 0.18s cubic-bezier(0.22, 1, 0.36, 1), border-color 0.18s ease,
    box-shadow 0.18s ease;
  pointer-events: none;
}

.ctc--dragging .ctc__thumb {
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.ctc__ticks {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 0.18rem;
}

.ctc__tick {
  padding: 0.2rem 0;
  border: none;
  border-radius: 0.4rem;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(148, 163, 184, 0.7);
  font-size: 0.65rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  cursor: pointer;
  transition: color 0.16s ease, background 0.16s ease;
}

.ctc__tick:hover {
  color: rgba(248, 250, 252, 0.95);
  background: rgba(255, 255, 255, 0.08);
}

.ctc__tick--on {
  background: rgba(255, 255, 255, 0.1);
  font-weight: 800;
}

.ctc__tick:focus-visible {
  outline: 2px solid rgba(129, 140, 248, 0.65);
  outline-offset: 1px;
}

.ctc__sr {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

html[data-workbench-theme='light'] .ctc__label{color:#86868b}
html[data-workbench-theme='light'] .ctc__bar{box-shadow:inset 0 0 0 1px rgba(0,0,0,.06),0 1px 2px rgba(0,0,0,.08)}
html[data-workbench-theme='light'] .ctc__step{background:rgba(255,255,255,.55)}
html[data-workbench-theme='light'] .ctc__thumb{background:#fff;border-color:rgba(0,0,0,.12);color:#1d1d1f}
html[data-workbench-theme='light'] .ctc__tick{background:rgba(0,0,0,.03);color:#86868b}
html[data-workbench-theme='light'] .ctc__tick:hover{color:#1d1d1f;background:rgba(0,0,0,.06)}
html[data-workbench-theme='light'] .ctc__tick--on{background:rgba(0,113,227,.08)}
html[data-workbench-theme='light'] .ctc__track:focus-visible{outline-color:rgba(0,113,227,.5)}

</style>
