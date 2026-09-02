<script setup lang="ts">
// 拆分自 SelfEvolutionLoopRuntimePanel.vue 模板（原 meta 区块）；模板逐字迁移，行为不变。
defineProps<{
  cronLine: string
  evidenceCards: Array<{ label: string; value: string }>
  paraTaskId: string
  paraCopied: boolean
}>()

defineEmits<{ copy: [] }>()
</script>

<template>
    <div class="selp-meta" role="list" aria-label="loop 调度与证据">
      <div class="selp-meta-card" role="listitem">
        <span>每日调度</span>
        <strong>{{ cronLine }}</strong>
      </div>
      <div v-for="card in evidenceCards" :key="card.label" class="selp-meta-card" role="listitem">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <button
          v-if="card.label === 'Para task' && paraTaskId"
          type="button"
          class="selp-copy"
          @click="$emit('copy')"
        >
          {{ paraCopied ? '已复制' : '复制 ID' }}
        </button>
      </div>
    </div>
</template>

<style scoped src="./self-evolution-loop-runtime.css"></style>
