<script setup lang="ts">
defineProps<{
  cards: Array<{ key: string; label: string; value: string; sub: string }>
}>()
</script>

<template>
  <div class="selp-decision" role="list" aria-label="自动合并决策">
    <div v-for="card in cards" :key="card.key" class="selp-decision-card" role="listitem">
      <span>{{ card.label }}</span>
      <strong>{{ card.value }}</strong>
      <small>{{ card.sub }}</small>
    </div>
  </div>
</template>

<style scoped>
.selp-decision {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.selp-decision-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 10px 11px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.78);
}

.selp-decision-card span,
.selp-decision-card small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-decision-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 980px) {
  .selp-decision {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .selp-decision {
    grid-template-columns: 1fr;
  }
}
</style>