<script setup lang="ts">
import { asArray, type AnyRecord } from './runtimeHelpers'

// 拆分自 SelfEvolutionLoopRuntimePanel.vue 模板（原编制对齐区块）；模板逐字迁移，行为不变。
defineProps<{
  rosterAlignmentCards: Array<{ key: string; label: string; value: string; sub: string; tone: string }>
  rosterRemediation: AnyRecord
  rosterCoverage: AnyRecord[]
}>()
</script>

<template>
    <div class="selp-roster" aria-label="编制对齐与员工隔离">
      <div class="selp-roster-cards" role="list">
        <div v-for="card in rosterAlignmentCards" :key="card.key" class="selp-roster-card" :class="`selp-roster-card--${card.tone}`" role="listitem">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.sub }}</small>
        </div>
      </div>
      <div v-if="rosterRemediation.action && rosterRemediation.action !== 'none'" class="selp-roster-remediation">
        <div>
          <span>修复指引</span>
          <strong>{{ rosterRemediation.title || rosterRemediation.action }}</strong>
          <small>{{ rosterRemediation.detail || rosterRemediation.action }}</small>
        </div>
        <small v-if="asArray(rosterRemediation.target_employee_ids).length" class="selp-roster-remediation-ids">
          {{ asArray(rosterRemediation.target_employee_ids).slice(0, 6).join(' / ') }}
        </small>
      </div>
      <ul v-if="rosterCoverage.length" class="selp-roster-coverage">
        <li v-for="dept in rosterCoverage" :key="String(dept.key || dept.label)">
          <strong>{{ dept.label || dept.key }}</strong>
          <span>{{ dept.count ?? 0 }}/{{ dept.total ?? 0 }}</span>
          <small>{{ asArray(dept.ids).join(' / ') }}</small>
        </li>
      </ul>
    </div>
</template>

<style scoped src="./self-evolution-loop-runtime.css"></style>
