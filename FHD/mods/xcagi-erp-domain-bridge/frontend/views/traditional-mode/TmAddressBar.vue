<script setup lang="ts">
import type { TraditionalModeCtx } from './assemble'

// 拆分自 TraditionalModeView.vue 模板（原第 3–20 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: TraditionalModeCtx }>()

const {
  ROOT_NAME, pathSegments, pathInput, displayPath, navigateToSegment, goToPath,
} = props.tm
</script>

<template>
    <div class="address-bar">
      <span class="address-icon">📁</span>
      <div class="breadcrumb">
        <span class="breadcrumb-segment" @click="navigateToSegment(-1)">{{ ROOT_NAME }}</span>
        <template v-for="(seg, idx) in pathSegments" :key="idx">
          <span class="separator" aria-hidden="true">›</span>
          <span class="breadcrumb-segment" @click="navigateToSegment(idx)">{{ seg }}</span>
        </template>
      </div>
      <input
        v-model="pathInput"
        type="text"
        class="path-input"
        :placeholder="displayPath"
        @keydown.enter="goToPath"
      >
      <button class="btn-go" @click="goToPath">Go</button>
    </div>
</template>

<style scoped src="./traditional-mode.css"></style>
