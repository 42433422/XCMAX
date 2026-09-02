<script setup lang="ts">
// 缩放工具栏：由 StitchStage.vue 模板机械切分而来（行为保持不变）。
defineProps<{
  zoom: number
  minZoom: number
  maxZoom: number
  zoomStep: number
  zoomPct: number
}>()

const emit = defineEmits<{
  (e: 'zoom-in'): void
  (e: 'zoom-out'): void
  (e: 'reset'): void
  (e: 'zoom-input', event: Event): void
}>()
</script>

<template>
  <div class="stitch-stage-toolbar" role="toolbar" aria-label="缩放与中键平移说明">
    <button type="button" class="stitch-stage-btn" :disabled="zoom <= minZoom" @click="emit('zoom-out')">缩小</button>
    <label class="stitch-stage-zoom-label">
      <span class="stitch-stage-sr">缩放比例</span>
      <input
        class="stitch-stage-range"
        type="range"
        :min="minZoom * 100"
        :max="maxZoom * 100"
        :step="zoomStep * 100"
        :value="zoom * 100"
        @input="emit('zoom-input', $event)"
      />
      <span class="stitch-stage-zoom-readout" aria-hidden="true">{{ zoomPct }}%</span>
    </label>
    <button type="button" class="stitch-stage-btn" :disabled="zoom >= maxZoom" @click="emit('zoom-in')">放大</button>
    <button type="button" class="stitch-stage-btn stitch-stage-btn--ghost" title="缩放至可见整图" @click="emit('reset')">全图</button>
    <span class="stitch-stage-hint" aria-hidden="true">中键拖移</span>
  </div>
</template>

<style scoped src="./stitch-stage.css"></style>
