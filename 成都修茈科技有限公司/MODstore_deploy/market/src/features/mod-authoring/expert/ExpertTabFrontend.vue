<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

const { frontendEntryPath, frontendBrief, frontendBusy, regenerateFrontend } = useModAuthoringContext()
</script>

<template>
  <section class="panel">
    <div class="frontend-head">
      <h2 class="panel-title">前端</h2>
      <button
        type="button"
        class="btn btn-primary"
        :disabled="frontendBusy"
        @click="() => void regenerateFrontend()"
      >
        {{ frontendBusy ? '生成中…' : '重新生成' }}
      </button>
    </div>
    <p class="muted small">
      入口 <code class="mono">{{ frontendEntryPath || '未生成' }}</code>
    </p>
    <textarea
      v-model="frontendBrief"
      class="input textarea frontend-brief"
      rows="2"
      maxlength="8000"
      placeholder="生成说明（可选）"
    />
  </section>
</template>
