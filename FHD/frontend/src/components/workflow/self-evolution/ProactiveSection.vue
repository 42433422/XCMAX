<script setup lang="ts">
defineProps<{
  cards: Array<{ key: string; label: string; value: string; sub: string; tone: string }>
  candidates: Record<string, unknown>[]
  candidateTitle: (item: Record<string, unknown>) => string
  candidateMeta: (item: Record<string, unknown>) => string
}>()
</script>

<template>
  <div class="selp-proactive" aria-label="主动优化任务信号">
    <div class="selp-proactive-cards" role="list">
      <div v-for="card in cards" :key="card.key" class="selp-proactive-card" :class="`selp-proactive-card--${card.tone}`" role="listitem">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small>{{ card.sub }}</small>
      </div>
    </div>
    <ul v-if="candidates.length" class="selp-proactive-list">
      <li v-for="item in candidates" :key="`${candidateTitle(item)}-${candidateMeta(item)}`">
        <strong>{{ candidateTitle(item) }}</strong>
        <span>{{ candidateMeta(item) }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.selp-proactive {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid #e0e7ff;
  border-radius: 12px;
  background: radial-gradient(circle at 12% 0%, rgba(99, 102, 241, 0.11), transparent 36%), rgba(255, 255, 255, 0.78);
}

.selp-proactive-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.selp-proactive-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 9px 10px;
  border-radius: 10px;
  background: #f8fafc;
}

.selp-proactive-card--ok {
  background: #eef2ff;
}

.selp-proactive-card span,
.selp-proactive-card small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-proactive-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-proactive-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.selp-proactive-list li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.selp-proactive-list strong,
.selp-proactive-list span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-proactive-list strong {
  color: #312e81;
  font-size: 12px;
}

.selp-proactive-list span {
  color: #64748b;
  font-size: 11px;
}

@media (max-width: 980px) {
  .selp-proactive-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .selp-proactive-cards {
    grid-template-columns: 1fr;
  }
}
</style>
