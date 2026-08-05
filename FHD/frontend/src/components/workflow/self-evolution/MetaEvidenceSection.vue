<script setup lang="ts">
defineProps<{
  cronLine: string
  cards: Array<{ label: string; value: string }>
  paraTaskId: string
  paraCopied: boolean
  onCopyParaTaskId: () => void
}>()
defineEmits<{
  copy: []
}>()
</script>

<template>
  <div class="selp-meta" role="list" aria-label="循环调度与证据">
    <div class="selp-meta-card" role="listitem">
      <span>每日调度</span>
      <strong>{{ cronLine }}</strong>
    </div>
    <div v-for="card in cards" :key="card.label" class="selp-meta-card" role="listitem">
      <span>{{ card.label }}</span>
      <strong>{{ card.value }}</strong>
      <button
        v-if="card.label === 'Para 任务' && paraTaskId"
        type="button"
        class="selp-copy"
        @click="$emit('copy')"
      >
        {{ paraCopied ? '已复制' : '复制 ID' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.selp-meta {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.selp-meta-card {
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.82);
}

.selp-meta-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 11px;
}

.selp-meta-card span {
  color: var(--selp-muted);
  font-size: 12px;
  line-height: 1.35;
}

.selp-meta-card strong {
  overflow: hidden;
  color: var(--selp-text);
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-copy {
  align-self: flex-start;
  border: 1px solid #99f6e4;
  border-radius: 999px;
  background: #ecfeff;
  color: #0f766e;
  padding: 3px 7px;
  font-size: 11px;
  font-weight: 900;
  cursor: pointer;
}

@media (max-width: 980px) {
  .selp-meta {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .selp-meta {
    grid-template-columns: 1fr;
  }
}
</style>