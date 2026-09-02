<script setup lang="ts">
// 拆分自 SelfEvolutionLoopRuntimePanel.vue 模板（原进化指标区块）；模板逐字迁移，行为不变。
defineProps<{
  evolutionMetricCards: Array<{ key: string; label: string; value: string; sub: string; tone: string }>
  metricWindows: Array<Record<string, any>>
}>()
</script>

<template>
    <div class="selp-metrics" aria-label="进化指标与暂停门禁">
      <div class="selp-metrics-cards" role="list">
        <div v-for="card in evolutionMetricCards" :key="card.key" class="selp-metrics-card" :class="`selp-metrics-card--${card.tone}`" role="listitem">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.sub }}</small>
        </div>
      </div>
      <ul v-if="metricWindows.length" class="selp-metrics-windows">
        <li v-for="window in metricWindows" :key="`${window.from_week}-${window.to_week}`">
          <strong>{{ window.from_week || 'from' }} → {{ window.to_week || 'to' }}</strong>
          <span>
            coverage {{ window.coverage_delta ?? '—' }} · pytest {{ window.passed_delta ?? '—' }} · debt {{ window.debt_delta ?? '—' }}
          </span>
          <small v-if="Array.isArray(window.misses) && window.misses.length">{{ window.misses.join(' / ') }}</small>
        </li>
      </ul>
    </div>
</template>

<style scoped src="./self-evolution-loop-runtime.css"></style>
