<template>
  <div
    class="jarvis-core"
    :class="{
      speaking: isSpeaking,
      'work-mode': isWorkMode,
      'monitor-mode': isMonitorMode,
      'jarvis-core--reduce-effects': reduceEffects,
    }"
    :style="{ transform: coreTransform }"
  >
    <div class="jarvis-sphere"></div>
    <div class="icosa-core">
      <div
        v-for="(face, index) in icosaCoreFaces"
        :key="'icosa-core-' + index"
        class="icosa-core-face"
        :style="{ transform: face.transform, opacity: face.opacity }"
      ></div>
    </div>

    <!-- 待机时外层四套多面体不参与渲染，显著减轻合成层与 3D 变换开销 -->
    <template v-if="!reduceEffects">
      <div class="polyhedron icosa">
        <div
          v-for="(face, index) in icosaFaces"
          :key="'icosa-' + index"
          class="poly-face"
          :style="{ transform: face.transform, opacity: face.opacity }"
        ></div>
      </div>

      <div class="polyhedron octa">
        <div
          v-for="(face, index) in octaFaces"
          :key="'octa-' + index"
          class="poly-face"
          :style="{ transform: face.transform, opacity: face.opacity }"
        ></div>
      </div>

      <div class="polyhedron tetra">
        <div
          v-for="(face, index) in tetraFaces"
          :key="'tetra-' + index"
          class="poly-face"
          :style="{ transform: face.transform, opacity: face.opacity }"
        ></div>
      </div>

      <div class="polyhedron dodeca">
        <div
          v-for="(face, index) in dodecaFaces"
          :key="'dodeca-' + index"
          class="poly-face"
          :style="{ transform: face.transform, opacity: face.opacity }"
        ></div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps({
  isSpeaking: {
    type: Boolean,
    default: false,
  },
  isWorkMode: {
    type: Boolean,
    default: false,
  },
  isMonitorMode: {
    type: Boolean,
    default: false,
  },
  /** 待机减负：去掉外层旋转多面体，弱化光晕与阴影动画（仅保留呼吸缩放） */
  reduceEffects: {
    type: Boolean,
    default: false,
  },
})

const coreTransform = computed(() => `scale(${props.isSpeaking ? 1.1 : 1})`)

const icosaCoreFaces = [
  { transform: 'rotateY(0deg) rotateX(26deg) translateZ(46px)', opacity: 0.72 },
  { transform: 'rotateY(72deg) rotateX(26deg) translateZ(46px)', opacity: 0.66 },
  { transform: 'rotateY(144deg) rotateX(26deg) translateZ(46px)', opacity: 0.64 },
  { transform: 'rotateY(216deg) rotateX(26deg) translateZ(46px)', opacity: 0.62 },
  { transform: 'rotateY(288deg) rotateX(26deg) translateZ(46px)', opacity: 0.66 },
  { transform: 'rotateY(36deg) rotateX(-26deg) translateZ(46px)', opacity: 0.58 },
  { transform: 'rotateY(108deg) rotateX(-26deg) translateZ(46px)', opacity: 0.56 },
  { transform: 'rotateY(180deg) rotateX(-26deg) translateZ(46px)', opacity: 0.52 },
  { transform: 'rotateY(252deg) rotateX(-26deg) translateZ(46px)', opacity: 0.56 },
  { transform: 'rotateY(324deg) rotateX(-26deg) translateZ(46px)', opacity: 0.58 },
  { transform: 'rotateX(90deg) rotateY(0deg) translateZ(46px)', opacity: 0.64 },
  { transform: 'rotateX(90deg) rotateY(72deg) translateZ(46px)', opacity: 0.6 },
  { transform: 'rotateX(90deg) rotateY(144deg) translateZ(46px)', opacity: 0.56 },
  { transform: 'rotateX(90deg) rotateY(216deg) translateZ(46px)', opacity: 0.54 },
  { transform: 'rotateX(90deg) rotateY(288deg) translateZ(46px)', opacity: 0.6 },
  { transform: 'rotateX(-90deg) rotateY(36deg) translateZ(46px)', opacity: 0.54 },
  { transform: 'rotateX(-90deg) rotateY(108deg) translateZ(46px)', opacity: 0.5 },
  { transform: 'rotateX(-90deg) rotateY(180deg) translateZ(46px)', opacity: 0.48 },
  { transform: 'rotateX(-90deg) rotateY(252deg) translateZ(46px)', opacity: 0.5 },
  { transform: 'rotateX(-90deg) rotateY(324deg) translateZ(46px)', opacity: 0.54 },
]

const icosaFaces = [
  { transform: 'rotateX(0deg) rotateY(0deg) translateZ(96px)', opacity: 0.32 },
  { transform: 'rotateX(60deg) rotateY(0deg) translateZ(96px)', opacity: 0.24 },
  { transform: 'rotateX(-60deg) rotateY(0deg) translateZ(96px)', opacity: 0.24 },
  { transform: 'rotateX(0deg) rotateY(60deg) translateZ(96px)', opacity: 0.28 },
  { transform: 'rotateX(0deg) rotateY(-60deg) translateZ(96px)', opacity: 0.28 },
  { transform: 'rotateX(180deg) rotateY(0deg) translateZ(96px)', opacity: 0.18 },
]

const octaFaces = [
  { transform: 'rotateX(0deg) translateZ(78px)', opacity: 0.24 },
  { transform: 'rotateX(90deg) translateZ(78px)', opacity: 0.22 },
  { transform: 'rotateY(90deg) translateZ(78px)', opacity: 0.22 },
  { transform: 'rotateY(-90deg) translateZ(78px)', opacity: 0.2 },
  { transform: 'rotateX(45deg) translateZ(78px)', opacity: 0.18 },
  { transform: 'rotateX(-45deg) translateZ(78px)', opacity: 0.18 },
]

const tetraFaces = [
  { transform: 'rotateX(0deg) rotateY(0deg) translateZ(64px)', opacity: 0.18 },
  { transform: 'rotateX(60deg) rotateY(30deg) translateZ(64px)', opacity: 0.16 },
  { transform: 'rotateX(-60deg) rotateY(-30deg) translateZ(64px)', opacity: 0.16 },
  { transform: 'rotateX(180deg) translateZ(64px)', opacity: 0.14 },
]

const dodecaFaces = [
  { transform: 'rotateX(90deg) translateZ(112px)', opacity: 0.18 },
  { transform: 'rotateX(-90deg) translateZ(112px)', opacity: 0.14 },
  { transform: 'rotateY(0deg) rotateX(26deg) translateZ(112px)', opacity: 0.2 },
  { transform: 'rotateY(72deg) rotateX(26deg) translateZ(112px)', opacity: 0.18 },
  { transform: 'rotateY(144deg) rotateX(26deg) translateZ(112px)', opacity: 0.16 },
  { transform: 'rotateY(216deg) rotateX(26deg) translateZ(112px)', opacity: 0.16 },
  { transform: 'rotateY(288deg) rotateX(26deg) translateZ(112px)', opacity: 0.18 },
  { transform: 'rotateY(36deg) rotateX(-26deg) translateZ(112px)', opacity: 0.14 },
  { transform: 'rotateY(108deg) rotateX(-26deg) translateZ(112px)', opacity: 0.14 },
  { transform: 'rotateY(180deg) rotateX(-26deg) translateZ(112px)', opacity: 0.12 },
]
</script>

<style scoped>
.jarvis-core {
  position: relative;
  width: 160px;
  height: 160px;
  transform-style: preserve-3d;
  cursor: inherit;
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  /* 仅用 layout：若含 paint，光晕/box-shadow 会被裁成「方框」 especially 悬浮球缩放下 */
  contain: layout;
}

.jarvis-core:hover {
  transform: scale(1.05);
}

.jarvis-core::before {
  content: "";
  position: absolute;
  inset: -9%;
  border-radius: 50%;
  border: 1px solid rgba(125, 231, 255, 0.18);
  box-shadow:
    0 0 26px rgba(0, 220, 255, 0.16),
    inset 0 0 30px rgba(0, 220, 255, 0.08);
  animation: haloSpin 20s linear infinite;
  pointer-events: none;
}

.jarvis-sphere {
  position: absolute;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: radial-gradient(
    circle at 35% 35%,
    rgba(200, 255, 255, 0.9) 0%,
    rgba(0, 255, 255, 0.6) 10%,
    rgba(0, 180, 255, 0.3) 30%,
    rgba(0, 100, 180, 0.15) 60%,
    rgba(0, 50, 100, 0.05) 80%,
    transparent 100%
  );
  box-shadow:
    0 0 72px rgba(0, 255, 255, 0.92),
    0 0 138px rgba(0, 200, 255, 0.72),
    0 0 200px rgba(0, 150, 255, 0.46),
    0 0 260px rgba(0, 100, 200, 0.22),
    inset 0 0 88px rgba(0, 255, 255, 0.56),
    inset 0 0 110px rgba(0, 200, 255, 0.36);
  animation: coreBreath 4s ease-in-out infinite;
  /* 光晕固定在样式表：呼吸只(scale)走 transform，避免 keyframes 里改 box-shadow 触发大面积重绘 */
  transition: background 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.icosa-core {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 92px;
  height: 92px;
  margin-left: -46px;
  margin-top: -46px;
  transform-style: preserve-3d;
  pointer-events: none;
  z-index: 4;
  animation: coreIcosaRotate 11s linear infinite;
  filter: drop-shadow(0 0 14px rgba(0, 255, 255, 0.45));
}

.icosa-core-face {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 60px;
  height: 56px;
  margin-left: -30px;
  margin-top: -28px;
  clip-path: polygon(50% 0%, 0% 100%, 100% 100%);
  background: linear-gradient(160deg, rgba(212, 251, 255, 0.74), rgba(35, 212, 255, 0.2) 50%, rgba(5, 80, 120, 0.05));
  border: 1px solid rgba(130, 239, 255, 0.62);
  box-shadow:
    0 0 10px rgba(40, 225, 255, 0.38),
    inset 0 0 10px rgba(170, 245, 255, 0.25);
  backface-visibility: hidden;
}

.icosa-core-face::after {
  content: "";
  position: absolute;
  inset: 16% 20% 14%;
  border-top: 1px solid rgba(225, 250, 255, 0.65);
  transform: skewX(-16deg);
  opacity: 0.7;
}

.jarvis-sphere::before,
.jarvis-sphere::after {
  content: "";
  position: absolute;
  inset: 8%;
  border-radius: 50%;
  pointer-events: none;
}

.jarvis-sphere::before {
  border: 1px solid rgba(190, 255, 255, 0.5);
  box-shadow:
    inset 0 0 18px rgba(0, 255, 255, 0.22),
    0 0 26px rgba(0, 255, 255, 0.22);
}

.jarvis-sphere::after {
  inset: 22%;
  background: radial-gradient(circle, rgba(220, 255, 255, 0.34), rgba(0, 255, 255, 0.08) 55%, transparent 72%);
  animation: coreInnerPulse 2.8s ease-in-out infinite;
}

.work-mode .jarvis-sphere {
  background: radial-gradient(
    circle at 35% 35%,
    rgba(255, 200, 200, 0.9) 0%,
    rgba(255, 80, 80, 0.6) 10%,
    rgba(255, 100, 100, 0.3) 30%,
    rgba(180, 50, 50, 0.15) 60%,
    rgba(120, 30, 30, 0.05) 80%,
    transparent 100%
  );
  box-shadow:
    0 0 72px rgba(255, 80, 80, 0.92),
    0 0 138px rgba(220, 60, 60, 0.72),
    0 0 200px rgba(200, 50, 50, 0.46),
    0 0 260px rgba(180, 40, 40, 0.22),
    inset 0 0 88px rgba(255, 80, 80, 0.56),
    inset 0 0 110px rgba(220, 60, 60, 0.36);
  animation: coreBreathWork 4s ease-in-out infinite;
}

.work-mode .icosa-core {
  filter: drop-shadow(0 0 14px rgba(255, 105, 105, 0.5));
}

.work-mode .icosa-core-face {
  background: linear-gradient(160deg, rgba(255, 228, 228, 0.76), rgba(255, 88, 88, 0.28) 50%, rgba(130, 22, 22, 0.05));
  border-color: rgba(255, 142, 142, 0.72);
  box-shadow:
    0 0 10px rgba(255, 96, 96, 0.45),
    inset 0 0 10px rgba(255, 178, 178, 0.28);
}

.monitor-mode .jarvis-sphere {
  background: radial-gradient(
    circle at 35% 35%,
    rgba(255, 250, 210, 0.9) 0%,
    rgba(255, 215, 0, 0.6) 10%,
    rgba(255, 180, 0, 0.3) 34%,
    rgba(180, 120, 0, 0.14) 64%,
    transparent 100%
  );
  box-shadow:
    0 0 72px rgba(255, 215, 0, 0.88),
    0 0 138px rgba(255, 180, 0, 0.62),
    0 0 200px rgba(220, 140, 0, 0.42),
    inset 0 0 88px rgba(255, 215, 0, 0.52),
    inset 0 0 110px rgba(255, 180, 0, 0.32);
  animation: coreBreathMonitor 4s ease-in-out infinite;
}

.monitor-mode .icosa-core {
  filter: drop-shadow(0 0 14px rgba(255, 217, 90, 0.52));
}

.monitor-mode .icosa-core-face {
  background: linear-gradient(160deg, rgba(255, 245, 207, 0.78), rgba(255, 210, 80, 0.28) 52%, rgba(120, 80, 10, 0.05));
  border-color: rgba(255, 223, 126, 0.74);
  box-shadow:
    0 0 10px rgba(255, 214, 92, 0.42),
    inset 0 0 10px rgba(255, 240, 188, 0.28);
}

.jarvis-core.speaking .jarvis-sphere {
  animation: coreBreathSpeaking 1s ease-in-out infinite;
}

.jarvis-core.speaking .icosa-core {
  animation:
    coreIcosaRotateFast 1.6s linear infinite,
    coreIcosaPulse 1s ease-in-out infinite;
}

.work-mode.jarvis-core.speaking .jarvis-sphere {
  animation: coreBreathWorkSpeaking 1s ease-in-out infinite;
}

.monitor-mode.jarvis-core.speaking .jarvis-sphere {
  animation: coreBreathMonitorSpeaking 1s ease-in-out infinite;
}

.polyhedron {
  position: absolute;
  left: 50%;
  top: 50%;
  transform-style: preserve-3d;
  pointer-events: none;
  /* will-change 只在多面体实际挂载（非 reduce-effects）时生效；
     reduce-effects 时整段由 v-if 不挂载，此处声明安全 */
  will-change: transform;
  z-index: 2;
}

.polyhedron.icosa {
  width: 192px;
  height: 192px;
  margin-left: -96px;
  margin-top: -96px;
  animation: rotate3DIcosa 18s linear infinite;
}

.polyhedron.octa {
  width: 156px;
  height: 156px;
  margin-left: -78px;
  margin-top: -78px;
  animation: rotate3DOcta 14s linear infinite;
}

.polyhedron.tetra {
  width: 128px;
  height: 128px;
  margin-left: -64px;
  margin-top: -64px;
  animation: rotate3DTetra 20s linear infinite;
}

.polyhedron.dodeca {
  width: 224px;
  height: 224px;
  margin-left: -112px;
  margin-top: -112px;
  animation: rotate3DDodeca 24s linear infinite;
}

.poly-face {
  position: absolute;
  width: 100%;
  height: 100%;
  border: 1px solid rgba(0, 255, 255, 0.32);
  background: rgba(0, 255, 255, 0.08);
  backface-visibility: visible;
  box-shadow: inset 0 0 20px rgba(0, 255, 255, 0.1);
  border-radius: 10px;
  transition:
    border-color 0.3s cubic-bezier(0.4, 0, 0.2, 1),
    background 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.work-mode .poly-face {
  border-color: rgba(255, 0, 0, 0.5);
  background: rgba(255, 0, 0, 0.1);
}

.monitor-mode .poly-face {
  border-color: rgba(255, 215, 0, 0.55);
  background: rgba(255, 215, 0, 0.12);
}

@keyframes rotate3DIcosa {
  0% { transform: rotateX(0deg) rotateY(0deg) rotateZ(0deg); }
  100% { transform: rotateX(360deg) rotateY(360deg) rotateZ(0deg); }
}

@keyframes rotate3DOcta {
  0% { transform: rotateX(0deg) rotateY(0deg) rotateZ(0deg); }
  100% { transform: rotateX(0deg) rotateY(360deg) rotateZ(360deg); }
}

@keyframes rotate3DTetra {
  0% { transform: rotateX(0deg) rotateY(0deg) rotateZ(0deg); }
  100% { transform: rotateX(360deg) rotateY(0deg) rotateZ(360deg); }
}

@keyframes rotate3DDodeca {
  0% { transform: rotateX(0deg) rotateY(0deg) rotateZ(0deg); }
  100% { transform: rotateX(-360deg) rotateY(-360deg) rotateZ(0deg); }
}

@keyframes coreIcosaRotate {
  0% { transform: rotateX(0deg) rotateY(0deg) rotateZ(0deg); }
  100% { transform: rotateX(360deg) rotateY(360deg) rotateZ(0deg); }
}

@keyframes coreIcosaRotateFast {
  0% { transform: rotateX(0deg) rotateY(0deg) rotateZ(0deg); }
  100% { transform: rotateX(360deg) rotateY(360deg) rotateZ(360deg); }
}

@keyframes coreIcosaPulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.86;
  }
}

@keyframes haloSpin {
  0% { transform: rotate(0deg) scale(1); opacity: 0.75; }
  50% { transform: rotate(180deg) scale(1.03); opacity: 1; }
  100% { transform: rotate(360deg) scale(1); opacity: 0.75; }
}

/* 待机减负：外圈只旋转不改 opacity，减轻合成后的无效重绘 */
@keyframes jarvisHaloDrift {
  to {
    transform: rotate(360deg);
  }
}

@keyframes coreBreath {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.08);
  }
}

@keyframes coreBreathWork {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.08);
  }
}

@keyframes coreBreathMonitor {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.08);
  }
}

@keyframes coreInnerPulse {
  0%, 100% {
    opacity: 0.72;
    transform: scale(0.9);
  }
  50% {
    opacity: 1;
    transform: scale(1.08);
  }
}

@keyframes coreBreathSpeaking {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.1);
  }
}

@keyframes coreBreathWorkSpeaking {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.1);
  }
}

@keyframes coreBreathMonitorSpeaking {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.1);
  }
}

/* reduce-effects（idle）：简化构图 + 球体慢呼吸；扩散半径保持适中以兼顾观感与合成开销 */
.jarvis-core--reduce-effects::before {
  animation: jarvisHaloDrift 120s linear infinite;
  opacity: 0.52;
  box-shadow:
    0 0 16px rgba(0, 220, 255, 0.12),
    inset 0 0 22px rgba(0, 220, 255, 0.06);
  will-change: transform;
}

.jarvis-core--reduce-effects .jarvis-sphere {
  animation: jarvisIdleBreathScale 6s ease-in-out infinite;
  /* 待机：干净玻璃球体感，避免多层廉价霓虹；扩散仍控制在 ~80px 内 */
  background: radial-gradient(
    circle at 32% 30%,
    rgba(235, 255, 255, 0.95) 0%,
    rgba(120, 248, 255, 0.55) 18%,
    rgba(0, 210, 230, 0.35) 42%,
    rgba(0, 90, 140, 0.18) 68%,
    rgba(0, 35, 70, 0.06) 88%,
    transparent 100%
  );
  box-shadow:
    0 0 28px rgba(0, 245, 255, 0.42),
    0 0 52px rgba(0, 170, 220, 0.22),
    inset 0 0 44px rgba(180, 255, 255, 0.38),
    inset -12px -18px 36px rgba(0, 80, 120, 0.25);
}

.jarvis-core--reduce-effects .jarvis-sphere::before {
  inset: 10%;
  border-color: rgba(200, 255, 255, 0.35);
  box-shadow:
    inset 0 0 22px rgba(0, 220, 255, 0.18),
    0 0 18px rgba(0, 230, 255, 0.15);
}

.jarvis-core--reduce-effects .jarvis-sphere::after {
  inset: 26%;
  background: radial-gradient(circle at 40% 38%, rgba(255, 255, 255, 0.55), rgba(0, 230, 255, 0.12) 52%, transparent 72%);
  animation: jarvisIdleCoreGlint 5.5s ease-in-out infinite;
}

@keyframes jarvisIdleCoreGlint {
  0%,
  100% {
    opacity: 0.44;
    transform: scale(0.94);
  }
  50% {
    opacity: 0.68;
    transform: scale(1);
  }
}

/* 待机减负时去掉中心二十面体线框，避免与静止轨道叠成「铁丝球」 */
.jarvis-core--reduce-effects .icosa-core {
  display: none;
}

.jarvis-core--reduce-effects .icosa-core-face {
  box-shadow: none;
}

@keyframes jarvisIdleBreathScale {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.06);
  }
}

@media (prefers-reduced-motion: reduce) {
  .jarvis-core::before,
  .jarvis-sphere,
  .jarvis-sphere::after,
  .icosa-core,
  .polyhedron {
    animation: none !important;
  }

  .jarvis-core.speaking .icosa-core {
    animation: none !important;
  }

  .jarvis-core--reduce-effects .jarvis-sphere {
    animation: none !important;
  }
}
</style>
