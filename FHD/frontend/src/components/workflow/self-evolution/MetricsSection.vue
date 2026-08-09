<script setup lang="ts">
defineProps<{
  cards: Array<{ key: string; label: string; value: string; sub: string; tone: string }>
  windows: Array<Record<string, unknown>>
}>()
</script>

<template>
  <div class="selp-metrics" aria-label="进化指标与暂停门禁">
    <div class="selp-metrics-cards" role="list">
      <div v-for="card in cards" :key="card.key" class="selp-metrics-card" :class="`selp-metrics-card--${card.tone}`" role="listitem">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small>{{ card.sub }}</small>
      </div>
    </div>
    <ul v-if="windows.length" class="selp-metrics-windows">
      <li v-for="window in windows" :key="`${window.from_week}-${window.to_week}`">
        <strong>{{ window.from_week || '起始' }} → {{ window.to_week || '结束' }}</strong>
        <span>
          覆盖率 {{ window.coverage_delta ?? '—' }} · pytest {{ window.passed_delta ?? '—' }} · 债务 {{ window.debt_delta ?? '—' }}
        </span>
        <small v-if="Array.isArray(window.misses) && window.misses.length">{{ window.misses.join(' / ') }}</small>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.selp-metrics {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid #dcfce7;
  border-radius: 12px;
  background:
    radial-gradient(circle at 12% 0%, rgba(34, 197, 94, 0.10), transparent 36%),
    rgba(255, 255, 255, 0.78);
}

.selp-metrics-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.selp-metrics-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 9px 10px;
  border-radius: 10px;
  background: #f8fafc;
}

.selp-metrics-card--ok { background: #ecfdf5; }
.selp-metrics-card--warn { background: #fffbeb; }
.selp-metrics-card--bad { background: #fef2f2; }

.selp-metrics-card span,
.selp-metrics-card small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-metrics-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-metrics-windows {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.selp-metrics-windows li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.selp-metrics-windows strong,
.selp-metrics-windows span,
.selp-metrics-windows small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-metrics-windows strong {
  color: #14532d;
  font-size: 12px;
}

.selp-metrics-windows span,
.selp-metrics-windows small {
  color: #64748b;
  font-size: 11px;
}
</style>