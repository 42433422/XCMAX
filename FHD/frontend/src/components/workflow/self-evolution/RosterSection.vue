<script setup lang="ts">
import { asArray, type AnyRecord } from '@/composables/useLoopRuntimePanel'

defineProps<{
  cards: Array<{ key: string; label: string; value: string; sub: string; tone: string }>
  remediation: AnyRecord
  coverage: AnyRecord[]
}>()
</script>

<template>
  <div class="selp-roster" aria-label="排班匹配与员工隔离">
    <div class="selp-roster-cards" role="list">
      <div v-for="card in cards" :key="card.key" class="selp-roster-card" :class="`selp-roster-card--${card.tone}`" role="listitem">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small>{{ card.sub }}</small>
      </div>
    </div>
    <div v-if="remediation.action && remediation.action !== 'none'" class="selp-roster-remediation">
      <div>
        <span>修复指引</span>
        <strong>{{ remediation.title || remediation.action }}</strong>
        <small>{{ remediation.detail || remediation.action }}</small>
      </div>
      <small v-if="asArray(remediation.target_employee_ids).length" class="selp-roster-remediation-ids">
        {{ asArray(remediation.target_employee_ids).slice(0, 6).join(' / ') }}
      </small>
    </div>
    <ul v-if="coverage.length" class="selp-roster-coverage">
      <li v-for="dept in coverage" :key="String(dept.key || dept.label)">
        <strong>{{ dept.label || dept.key }}</strong>
        <span>{{ dept.count ?? 0 }}/{{ dept.total ?? 0 }}</span>
        <small>{{ asArray(dept.ids).join(' / ') }}</small>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.selp-roster {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid #ccfbf1;
  border-radius: 12px;
  background: radial-gradient(circle at 12% 0%, rgba(20, 184, 166, 0.1), transparent 36%), rgba(255, 255, 255, 0.78);
}

.selp-roster-cards {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
}

.selp-roster-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 9px 10px;
  border-radius: 10px;
  background: #f8fafc;
}

.selp-roster-card--run {
  background: #ecfeff;
}
.selp-roster-card--ok {
  background: #f0fdf4;
}
.selp-roster-card--warn {
  background: #fffbeb;
}
.selp-roster-card--bad {
  background: #fef2f2;
}

.selp-roster-card span,
.selp-roster-card small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-roster-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-roster-remediation {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 9px 10px;
  border: 1px solid #fed7aa;
  border-radius: 10px;
  background: #fffbeb;
}

.selp-roster-remediation div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.selp-roster-remediation span,
.selp-roster-remediation small {
  overflow: hidden;
  color: #92400e;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-roster-remediation strong {
  overflow: hidden;
  color: #78350f;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-roster-remediation-ids {
  max-width: 340px;
  padding: 5px 8px;
  border-radius: 8px;
  background: rgba(153, 27, 27, 0.08);
  color: #991b1b !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 900;
}

.selp-roster-coverage {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.selp-roster-coverage li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 8px;
  min-width: 0;
  padding: 7px 8px;
  border-radius: 9px;
  background: rgba(240, 253, 250, 0.72);
}

.selp-roster-coverage strong,
.selp-roster-coverage span,
.selp-roster-coverage small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-roster-coverage strong {
  color: #0f766e;
  font-size: 12px;
}

.selp-roster-coverage span,
.selp-roster-coverage small {
  color: #64748b;
  font-size: 11px;
}

.selp-roster-coverage small {
  grid-column: 1 / -1;
}

@media (max-width: 760px) {
  .selp-roster-cards,
  .selp-roster-coverage {
    grid-template-columns: 1fr;
  }
}
</style>
