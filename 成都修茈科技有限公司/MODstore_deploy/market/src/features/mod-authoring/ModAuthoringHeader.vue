<script setup lang="ts">
import ModAuthoringModeToggle from './ModAuthoringModeToggle.vue'
import { useModAuthoringContext } from './composables/useModAuthoringContext'

defineProps<{
  expertMode: boolean
}>()

const emit = defineEmits<{
  'update:expertMode': [value: boolean]
}>()

const { modData, goRepo } = useModAuthoringContext()
</script>

<template>
  <header class="page-header">
    <div class="header-top">
      <button type="button" class="btn btn-ghost" @click="goRepo">← Mod 仓库</button>
      <span
        class="badge"
        :class="modData?.validation_ok ? 'badge-ok' : 'badge-warn'"
      >
        {{ modData?.validation_ok ? '已通过' : '待修正' }}
      </span>
      <div class="header-top-spacer" />
      <ModAuthoringModeToggle :expert-mode="expertMode" @update:expert-mode="emit('update:expertMode', $event)" />
    </div>
    <h1 class="page-title">{{ modData?.manifest?.name || modData?.id }}</h1>
    <p class="page-sub">
      <code class="mono">{{ modData?.id }}</code>
      <span v-if="modData?.manifest?.version" class="muted"> · v{{ modData.manifest.version }}</span>
    </p>
  </header>
</template>

<style scoped>
.header-top-spacer {
  flex: 1;
}
.header-top {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}
</style>
