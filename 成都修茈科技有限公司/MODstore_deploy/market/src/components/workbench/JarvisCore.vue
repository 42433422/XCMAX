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

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./JarvisCore.css，模板与逻辑保持原样。 -->
<style scoped src="./JarvisCore.css"></style>

