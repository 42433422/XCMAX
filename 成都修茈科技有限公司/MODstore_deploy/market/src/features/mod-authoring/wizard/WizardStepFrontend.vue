<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

const emit = defineEmits<{
  skip: []
}>()

const {
  frontendEntryPath,
  frontendBrief,
  frontendBusy,
  regenerateFrontend,
  fileSet,
} = useModAuthoringContext()
</script>

<template>
  <section class="panel wizard-panel">
    <h2 class="panel-title">界面</h2>
    <p class="muted small">
      入口 <code class="mono">{{ frontendEntryPath || '未生成' }}</code>
      <span v-if="fileSet.has('frontend/routes.js')"> · 已有 routes.js</span>
    </p>
    <input v-model="frontendBrief" class="input" placeholder="生成说明（可选）" />
    <div class="wizard-actions-inline">
      <button type="button" class="btn btn-primary" :disabled="frontendBusy" @click="regenerateFrontend">
        {{ frontendBusy ? '生成中…' : '生成前端' }}
      </button>
      <button type="button" class="btn btn-ghost" @click="emit('skip')">跳过</button>
    </div>
  </section>
</template>
