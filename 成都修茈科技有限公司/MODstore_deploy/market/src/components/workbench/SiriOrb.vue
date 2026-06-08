<template>
  <div class="siri-orb-wrap">
    <svg class="siri-progress-ring" viewBox="0 0 200 200">
      <circle
        class="siri-progress-ring__bg"
        cx="100"
        cy="100"
        r="96"
        fill="none"
        stroke="rgba(255,255,255,0.06)"
        stroke-width="2"
      />
      <circle
        class="siri-progress-ring__fill"
        cx="100"
        cy="100"
        r="96"
        fill="none"
        :stroke="ringColor"
        stroke-width="2"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="dashOffset"
      />
    </svg>
    <div class="siri-orb-outer" :style="orbOuterStyle">
      <div :class="orbClass">
        <div class="siri-blob siri-blob--1"></div>
        <div class="siri-blob siri-blob--2"></div>
        <div class="siri-blob siri-blob--3"></div>
        <div class="siri-blob siri-blob--4"></div>
        <div class="siri-blob siri-blob--5"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  mode: {
    type: String,
    default: 'idle',
    validator: (v) => ['idle', 'listening', 'processing', 'reporting'].includes(v)
  },
  progress: {
    type: Number,
    default: 0,
    validator: (v) => v >= 0 && v <= 100
  },
  audioLevel: {
    type: Number,
    default: 0,
    validator: (v) => v >= 0 && v <= 1
  }
})

const themeColors = {
  idle:       { accent: '#8b5cf6' },
  listening:  { accent: '#22c55e' },
  processing: { accent: '#7c3aed' },
  reporting:  { accent: '#f59e0b' }
}

const ringColor = computed(() => themeColors[props.mode]?.accent ?? '#8b5cf6')

const circumference = 2 * Math.PI * 96

const dashOffset = computed(() => {
  const pct = Math.min(Math.max(props.progress, 0), 100)
  return circumference - (circumference * pct) / 100
})

/** 滞后阈值，避免 audioLevel 在边界抖动时 orb 动画类名来回切换 */
const soundActive = ref(false)
watch(
  () => props.audioLevel,
  (level) => {
    if (level >= 0.06) soundActive.value = true
    else if (level <= 0.025) soundActive.value = false
  },
  { immediate: true },
)
watch(
  () => props.mode,
  (mode) => {
    if (mode !== 'listening') soundActive.value = false
  },
)

const hasSound = computed(() => props.mode === 'listening' && soundActive.value)

const orbOuterStyle = computed(() => {
  const level = hasSound.value ? props.audioLevel : 0
  const s = 1 + level * 0.18
  const sx = level * 4
  const sy = level * -3
  return {
    '--au-s': s,
    '--au-sx': `${sx}deg`,
    '--au-sy': `${sy}deg`
  }
})

const orbClass = computed(() => {
  const base = 'siri-orb'
  if (props.mode === 'listening') {
    return `${base} siri-orb--listening${hasSound.value ? '' : ' siri-orb--listening-idle'}`
  }
  return `${base} siri-orb--${props.mode}`
})
</script>

<style scoped>
.siri-orb-wrap {
  position: relative;
  width: 200px;
  height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.siri-progress-ring {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
  pointer-events: none;
}

.siri-progress-ring__fill {
  transition: stroke-dashoffset 0.4s ease, stroke 0.6s ease;
}

.siri-orb-outer {
  width: 160px;
  height: 160px;
  transform: scale(var(--au-s, 1)) skewX(var(--au-sx, 0deg)) skewY(var(--au-sy, 0deg));
  transition: transform 0.12s ease-out;
  display: flex;
  align-items: center;
  justify-content: center;
}

.siri-orb {
  position: relative;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.15);
}

.siri-orb--idle {
  animation: siri-breathe 4s ease-in-out infinite;
}
.siri-orb--listening {
  animation: siri-bounce 0.9s ease-in-out infinite;
}
.siri-orb--listening-static {
  animation: none;
  transform: scale(1);
}
.siri-orb--listening-static .siri-blob {
  animation: none !important;
}
.siri-orb--listening-idle {
  animation: siri-breathe 2.8s ease-in-out infinite;
}
.siri-orb--listening-idle .siri-blob {
  animation-duration: 4.5s;
}
.siri-orb--processing {
  animation: siri-pulse 1.4s ease-in-out infinite;
}
.siri-orb--reporting {
  animation: siri-flow 4s ease-in-out infinite;
}

.siri-blob {
  position: absolute;
  border-radius: 50%;
  will-change: transform, opacity;
  transition: background 0.6s ease, opacity 0.6s ease;
}

.siri-blob--1 {
  width: 110%;
  height: 110%;
  top: -5%;
  left: -5%;
  opacity: 0.85;
  filter: blur(28px);
  animation: siri-orbit1 3.2s ease-in-out infinite;
}
.siri-blob--2 {
  width: 90%;
  height: 90%;
  top: 5%;
  left: 5%;
  opacity: 0.75;
  filter: blur(32px);
  animation: siri-orbit2 4.1s ease-in-out infinite;
}
.siri-blob--3 {
  width: 75%;
  height: 75%;
  top: 12%;
  left: 12%;
  opacity: 0.7;
  filter: blur(24px);
  animation: siri-orbit3 5.3s ease-in-out infinite;
}
.siri-blob--4 {
  width: 65%;
  height: 65%;
  top: 18%;
  left: 18%;
  opacity: 0.65;
  filter: blur(20px);
  animation: siri-orbit4 3.8s ease-in-out infinite;
}
.siri-blob--5 {
  width: 50%;
  height: 50%;
  top: 25%;
  left: 25%;
  opacity: 0.55;
  filter: blur(16px);
  animation: siri-orbit5 4.7s ease-in-out infinite;
}

.siri-orb--idle .siri-blob--1 { background: radial-gradient(circle at 30% 30%, #6366f1, #8b5cf6); }
.siri-orb--idle .siri-blob--2 { background: radial-gradient(circle at 70% 70%, #818cf8, #6366f1); }
.siri-orb--idle .siri-blob--3 { background: radial-gradient(circle at 50% 20%, #a78bfa, #7c3aed); }
.siri-orb--idle .siri-blob--4 { background: radial-gradient(circle at 40% 80%, #7c3aed, #6366f1); }
.siri-orb--idle .siri-blob--5 { background: radial-gradient(circle at 60% 50%, #c4b5fd, #8b5cf6); }

.siri-orb--listening .siri-blob--1 { background: radial-gradient(circle at 30% 30%, #06b6d4, #22c55e); }
.siri-orb--listening .siri-blob--2 { background: radial-gradient(circle at 70% 70%, #22c55e, #06b6d4); }
.siri-orb--listening .siri-blob--3 { background: radial-gradient(circle at 50% 20%, #34d399, #0ea5e9); }
.siri-orb--listening .siri-blob--4 { background: radial-gradient(circle at 40% 80%, #0ea5e9, #22c55e); }
.siri-orb--listening .siri-blob--5 { background: radial-gradient(circle at 60% 50%, #67e8f9, #10b981); }

.siri-orb--processing .siri-blob--1 { background: radial-gradient(circle at 30% 30%, #7c3aed, #6366f1); }
.siri-orb--processing .siri-blob--2 { background: radial-gradient(circle at 70% 70%, #6366f1, #22c55e); }
.siri-orb--processing .siri-blob--3 { background: radial-gradient(circle at 50% 20%, #818cf8, #10b981); }
.siri-orb--processing .siri-blob--4 { background: radial-gradient(circle at 40% 80%, #22c55e, #7c3aed); }
.siri-orb--processing .siri-blob--5 { background: radial-gradient(circle at 60% 50%, #a78bfa, #34d399); }

.siri-orb--reporting .siri-blob--1 { background: radial-gradient(circle at 30% 30%, #f59e0b, #fbbf24); }
.siri-orb--reporting .siri-blob--2 { background: radial-gradient(circle at 70% 70%, #fbbf24, #f59e0b); }
.siri-orb--reporting .siri-blob--3 { background: radial-gradient(circle at 50% 20%, #fcd34d, #d97706); }
.siri-orb--reporting .siri-blob--4 { background: radial-gradient(circle at 40% 80%, #d97706, #fbbf24); }
.siri-orb--reporting .siri-blob--5 { background: radial-gradient(circle at 60% 50%, #fde68a, #b45309); }

@keyframes siri-breathe {
  0%, 100% { transform: scale(0.96); }
  50% { transform: scale(1.04); }
}
@keyframes siri-bounce {
  0%, 100% { transform: scale(1); }
  25% { transform: scale(1.1); }
  50% { transform: scale(0.93); }
  75% { transform: scale(1.05); }
}
@keyframes siri-pulse {
  0%, 100% { transform: scale(1); }
  30% { transform: scale(1.08); }
  60% { transform: scale(0.95); }
}
@keyframes siri-flow {
  0%, 100% { transform: scale(1) rotate(0deg); }
  25% { transform: scale(1.03) rotate(2deg); }
  50% { transform: scale(0.98) rotate(0deg); }
  75% { transform: scale(1.01) rotate(-2deg); }
}

@keyframes siri-orbit1 {
  0% { transform: translate(0, 0) scale(1); }
  20% { transform: translate(18%, -12%) scale(1.08); }
  40% { transform: translate(-8%, 20%) scale(0.92); }
  60% { transform: translate(-20%, -8%) scale(1.04); }
  80% { transform: translate(10%, 14%) scale(0.96); }
  100% { transform: translate(0, 0) scale(1); }
}
@keyframes siri-orbit2 {
  0% { transform: translate(0, 0) scale(1); }
  20% { transform: translate(-16%, 18%) scale(0.94); }
  40% { transform: translate(14%, -10%) scale(1.06); }
  60% { transform: translate(10%, 16%) scale(0.97); }
  80% { transform: translate(-12%, -14%) scale(1.03); }
  100% { transform: translate(0, 0) scale(1); }
}
@keyframes siri-orbit3 {
  0% { transform: translate(0, 0) scale(1); }
  20% { transform: translate(12%, 16%) scale(1.05); }
  40% { transform: translate(-18%, -8%) scale(0.95); }
  60% { transform: translate(-8%, -18%) scale(1.02); }
  80% { transform: translate(16%, 8%) scale(0.98); }
  100% { transform: translate(0, 0) scale(1); }
}
@keyframes siri-orbit4 {
  0% { transform: translate(0, 0) scale(1); }
  20% { transform: translate(-10%, -16%) scale(0.97); }
  40% { transform: translate(16%, 12%) scale(1.04); }
  60% { transform: translate(8%, -12%) scale(0.99); }
  80% { transform: translate(-14%, 10%) scale(1.01); }
  100% { transform: translate(0, 0) scale(1); }
}
@keyframes siri-orbit5 {
  0% { transform: translate(0, 0) scale(1); }
  20% { transform: translate(14%, -14%) scale(1.06); }
  40% { transform: translate(-12%, 18%) scale(0.93); }
  60% { transform: translate(18%, 10%) scale(1.03); }
  80% { transform: translate(-6%, -16%) scale(0.97); }
  100% { transform: translate(0, 0) scale(1); }
}

html[data-workbench-theme='light'] .siri-orb {
  background: rgba(240, 240, 255, 0.25);
}
html[data-workbench-theme='light'] .siri-orb-wrap {
  filter: brightness(0.8) saturate(1.3);
}
</style>
