<template>
  <div
    class="orbit-rings"
    :class="[`orbit-rings--${modeClass}`, { 'orbit-rings--lite': lite }]"
    aria-hidden="true"
  >
    <div
      v-for="ring in wireRings"
      :key="ring.className"
      class="orbit-rings__wire"
      :class="ring.className"
    ></div>
    <div
      v-for="(ring, index) in toolRings"
      :key="ring.className"
      class="orbit-rings__tool"
      :class="ring.className"
    >
      <svg
        class="orbit-rings__tool-svg"
        viewBox="0 0 520 520"
        focusable="false"
      >
        <defs>
          <path
            :id="`wbVoiceToolRingPath-${index}`"
            d="M 260 42 A 218 218 0 1 1 259.9 42"
          />
        </defs>
        <text class="orbit-rings__tool-text">
          <textPath :href="`#wbVoiceToolRingPath-${index}`" :startOffset="ring.startOffset">
            {{ ring.text }}
          </textPath>
        </text>
      </svg>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps({
  /** Matches workbench voiceState: idle | listening | thinking | summary */
  mode: {
    type: String,
    default: 'idle',
  },
  /** 待机时减少环层数、弱化滤镜动画，降低 GPU/合成开销 */
  lite: {
    type: Boolean,
    default: false,
  },
})

const wireRings = [
  { className: 'ring-1' },
  { className: 'ring-2 ring-dashed' },
  { className: 'ring-3 ring-tilt-1' },
  { className: 'ring-4 ring-tilt-2' },
  { className: 'ring-5' },
  { className: 'ring-6 ring-dashed' },
  { className: 'ring-7' },
  { className: 'ring-8 ring-dashed' },
]

const toolRings = [
  {
    className: 'tool-ring-1',
    startOffset: '3%',
    text: 'VOICE PLAN  语音规划  需求澄清  任务拆解  制作交接  ',
  },
  {
    className: 'tool-ring-2',
    startOffset: '18%',
    text: 'TEXT FALLBACK  文字补充  生成确认  打开制作  WORKBENCH  ',
  },
]

const modeClass = computed(() => {
  const m = props.mode
  if (m === 'thinking' || m === 'summary') return m
  return 'cyan'
})
</script>

<style scoped>
.orbit-rings {
  position: absolute;
  top: 50%;
  left: 50%;
  width: min(34rem, 76vw);
  aspect-ratio: 1;
  transform: translate(-50%, -50%);
  z-index: 0;
  pointer-events: none;
  display: grid;
  place-items: center;
  transform-style: preserve-3d;
  perspective: 1000px;
  /* 限制内部 filter/shadow 的重绘范围，不向外传导 */
  contain: paint;
}

.orbit-rings__wire {
  position: absolute;
  top: 50%;
  left: 50%;
  border-radius: 50%;
  border: 1px solid var(--orbit-border, rgba(0, 255, 255, 0.35));
  opacity: 1;
  transform-origin: center center;
  animation: wbVoiceRingRotate linear infinite;
  transition:
    border-color 0.35s cubic-bezier(0.4, 0, 0.2, 1),
    box-shadow 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}

.orbit-rings:not(.orbit-rings--lite) .orbit-rings__wire {
  will-change: transform;
}

.orbit-rings__wire.ring-1 {
  width: 37%;
  height: 37%;
  border-width: 3px;
  border-color: var(--orbit-strong, rgba(0, 255, 255, 0.9));
  box-shadow:
    0 0 20px var(--orbit-glow-strong, rgba(0, 255, 255, 0.6)),
    0 0 40px var(--orbit-glow, rgba(0, 200, 255, 0.4)),
    inset 0 0 15px var(--orbit-inset, rgba(0, 255, 255, 0.2));
  animation-duration: 8s;
  z-index: 11;
}

/* 待机轻量：仅两圈细线 + 极慢旋转（animation 只用 transform），远比冻结阴影/多层文字便宜 */

.orbit-rings--lite .orbit-rings__wire.ring-3,
.orbit-rings--lite .orbit-rings__wire.ring-4,
.orbit-rings--lite .orbit-rings__wire.ring-5,
.orbit-rings--lite .orbit-rings__wire.ring-6,
.orbit-rings--lite .orbit-rings__wire.ring-7,
.orbit-rings--lite .orbit-rings__wire.ring-8 {
  display: none;
}

/* 待机：去掉弧形文字环（暂停后易糊成脏边），只保留少量同心线 */
.orbit-rings--lite .orbit-rings__tool {
  display: none;
}

.orbit-rings--lite .orbit-rings__wire.ring-1 {
  border-width: 2px;
  animation-duration: 96s;
  will-change: transform;
  box-shadow:
    0 0 14px var(--orbit-glow-strong, rgba(0, 255, 255, 0.38)),
    inset 0 0 12px var(--orbit-inset, rgba(0, 255, 255, 0.12));
}

.orbit-rings--lite .orbit-rings__wire.ring-2 {
  opacity: 0.55;
  animation-duration: 132s;
  will-change: transform;
}

.orbit-rings__wire.ring-2 {
  width: 44%;
  height: 44%;
  border-width: 2px;
  animation-duration: 10s;
  animation-direction: reverse;
  z-index: 10;
}

.orbit-rings__wire.ring-3 {
  width: 51%;
  height: 51%;
  border-width: 2px;
  animation-duration: 12s;
  animation-name: wbVoiceRingRotateTiltX;
  z-index: 9;
}

.orbit-rings__wire.ring-4 {
  width: 58%;
  height: 58%;
  border-width: 2px;
  border-style: dotted;
  animation-duration: 14s;
  animation-direction: reverse;
  animation-name: wbVoiceRingRotateTiltY;
  z-index: 8;
}

.orbit-rings__wire.ring-5 {
  width: 65%;
  height: 65%;
  opacity: 0.82;
  animation-duration: 16s;
  z-index: 7;
}

.orbit-rings__wire.ring-6 {
  width: 72%;
  height: 72%;
  opacity: 0.72;
  animation-duration: 18s;
  animation-direction: reverse;
  z-index: 6;
}

.orbit-rings__wire.ring-7 {
  width: 79%;
  height: 79%;
  opacity: 0.62;
  animation-duration: 20s;
  z-index: 5;
}

.orbit-rings__wire.ring-8 {
  width: 86%;
  height: 86%;
  opacity: 0.52;
  animation-duration: 22s;
  animation-direction: reverse;
  animation-name: wbVoiceRingRotate;
  /* 呼吸不再动画 box-shadow（外圈已有多层），保留中等强度静态光晕 */
  box-shadow:
    0 0 8px var(--orbit-glow, rgba(0, 255, 255, 0.26)),
    inset 0 0 5px var(--orbit-inset, rgba(0, 255, 255, 0.09));
  z-index: 4;
}

.orbit-rings__wire.ring-dashed {
  border-style: dashed;
}

.orbit-rings__wire.ring-tilt-1 {
  transform: translate(-50%, -50%) rotateX(68deg);
}

.orbit-rings__wire.ring-tilt-2 {
  transform: translate(-50%, -50%) rotateY(68deg);
}

.orbit-rings__tool {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 96%;
  height: 96%;
  transform-style: preserve-3d;
  transform-origin: center center;
  z-index: 12;
}

.orbit-rings:not(.orbit-rings--lite) .orbit-rings__tool {
  will-change: transform;
}

.orbit-rings__tool.tool-ring-1 {
  width: 90%;
  height: 90%;
  transform: translate(-50%, -50%) rotateX(64deg) rotateZ(0deg) skewY(6deg) skewX(3deg);
  animation: wbVoiceCodeRingRotate1 18s linear infinite;
}

.orbit-rings__tool.tool-ring-2 {
  width: 105%;
  height: 105%;
  transform: translate(-50%, -50%) rotateX(72deg) rotateY(12deg) rotateZ(360deg) skewY(-5deg) skewX(-3deg);
  animation: wbVoiceCodeRingRotate2 24s linear infinite reverse;
}

.orbit-rings__tool-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}

.orbit-rings__tool-text {
  font-family: Consolas, "Courier New", monospace;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 4px;
  fill: var(--orbit-text, rgba(0, 255, 255, 0.9));
  filter:
    drop-shadow(0 0 5px var(--orbit-text-glow, rgba(0, 255, 255, 0.8)))
    drop-shadow(0 0 10px var(--orbit-glow, rgba(0, 255, 255, 0.5)));
  animation: wbVoiceToolNameFlicker 2s ease-in-out infinite;
}

.orbit-rings--cyan {
  --orbit-border: rgba(0, 255, 255, 0.35);
  --orbit-glow: rgba(0, 255, 255, 0.22);
  --orbit-strong: rgba(0, 255, 255, 0.9);
  --orbit-glow-strong: rgba(0, 255, 255, 0.6);
  --orbit-inset: rgba(0, 255, 255, 0.2);
  --orbit-text: rgba(0, 255, 255, 0.9);
  --orbit-text-glow: rgba(0, 255, 255, 0.8);
}

.orbit-rings--thinking {
  --orbit-border: rgba(255, 80, 80, 0.42);
  --orbit-glow: rgba(255, 80, 80, 0.25);
  --orbit-strong: rgba(255, 120, 120, 0.92);
  --orbit-glow-strong: rgba(255, 80, 80, 0.55);
  --orbit-inset: rgba(255, 80, 80, 0.18);
  --orbit-text: rgba(255, 120, 120, 0.95);
  --orbit-text-glow: rgba(255, 80, 80, 0.82);
}

.orbit-rings--summary {
  --orbit-border: rgba(255, 215, 0, 0.45);
  --orbit-glow: rgba(255, 215, 0, 0.28);
  --orbit-strong: rgba(255, 215, 0, 0.88);
  --orbit-glow-strong: rgba(255, 215, 0, 0.55);
  --orbit-inset: rgba(255, 215, 0, 0.18);
  --orbit-text: rgba(255, 228, 120, 0.95);
  --orbit-text-glow: rgba(255, 215, 0, 0.72);
}

@keyframes wbVoiceRingRotate {
  0% { transform: translate(-50%, -50%) rotate(0deg); }
  100% { transform: translate(-50%, -50%) rotate(360deg); }
}

@keyframes wbVoiceRingRotateTiltX {
  0% { transform: translate(-50%, -50%) rotateX(68deg) rotateZ(0deg); }
  100% { transform: translate(-50%, -50%) rotateX(68deg) rotateZ(360deg); }
}

@keyframes wbVoiceRingRotateTiltY {
  0% { transform: translate(-50%, -50%) rotateY(68deg) rotateZ(360deg); }
  100% { transform: translate(-50%, -50%) rotateY(68deg) rotateZ(0deg); }
}

@keyframes wbVoiceCodeRingRotate1 {
  0% { transform: translate(-50%, -50%) rotateX(64deg) rotateZ(0deg) skewY(6deg) skewX(3deg); }
  100% { transform: translate(-50%, -50%) rotateX(64deg) rotateZ(360deg) skewY(6deg) skewX(3deg); }
}

@keyframes wbVoiceCodeRingRotate2 {
  0% { transform: translate(-50%, -50%) rotateX(72deg) rotateY(12deg) rotateZ(360deg) skewY(-5deg) skewX(-3deg); }
  100% { transform: translate(-50%, -50%) rotateX(72deg) rotateY(12deg) rotateZ(0deg) skewY(-5deg) skewX(-3deg); }
}

@keyframes wbVoiceToolNameFlicker {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.42; }
}

@media (prefers-reduced-motion: reduce) {
  .orbit-rings__wire,
  .orbit-rings__tool,
  .orbit-rings__tool-text {
    animation: none;
  }

  .orbit-rings--lite .orbit-rings__wire.ring-5,
  .orbit-rings--lite .orbit-rings__wire.ring-6,
  .orbit-rings--lite .orbit-rings__wire.ring-7,
  .orbit-rings--lite .orbit-rings__wire.ring-8 {
    display: none;
  }
}
</style>
