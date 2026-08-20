<script setup lang="ts">
import { asArray, firstText, type AnyRecord } from '@/composables/useLoopRuntimePanel'

defineProps<{
  recent: AnyRecord[]
  summary: AnyRecord
  summaryText: (row: AnyRecord) => string
}>()
</script>

<template>
  <div v-if="recent.length" class="selp-governance-audit" aria-label="最近治理动作">
    <div class="selp-governance-audit-head">
      <span>操作审计</span>
      <strong>{{ firstText(summary.health, '正常') }} · {{ recent.length }}</strong>
      <small
        >{{ summary.success_count ?? 0 }} 正常 · {{ summary.failure_count ?? 0 }} 失败 · 连续 {{ summary.consecutive_failures ?? 0 }}</small
      >
    </div>
    <ul>
      <li v-for="item in recent.slice().reverse().slice(0, 5)" :key="`${item.created_at || item.action}-${item.exit_code ?? ''}`">
        <span>{{ item.action || '治理' }}</span>
        <strong>{{ item.status || (item.ok === false ? '失败' : '成功') }}</strong>
        <small
          >{{ summaryText(item)
          }}<template v-if="asArray(item.target_employee_ids).length">
            ·
            {{
              asArray(item.target_employee_ids)
                .map((id) => String(id))
                .slice(0, 3)
                .join(' / ')
            }}</template
          ></small
        >
      </li>
    </ul>
  </div>
</template>

<style scoped>
.selp-governance-audit {
  display: grid;
  grid-template-columns: minmax(190px, 0.45fr) minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  background: rgba(239, 246, 255, 0.78);
}

.selp-governance-audit-head,
.selp-governance-audit li {
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.68);
}

.selp-governance-audit-head span,
.selp-governance-audit-head small,
.selp-governance-audit li span,
.selp-governance-audit li small {
  color: var(--selp-muted);
  font-size: 11px;
}

.selp-governance-audit-head strong,
.selp-governance-audit li strong {
  display: block;
  margin: 2px 0;
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
}

.selp-governance-audit ul {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

@media (max-width: 760px) {
  .selp-governance-audit {
    grid-template-columns: 1fr;
  }

  .selp-governance-audit ul {
    grid-template-columns: 1fr;
  }
}
</style>
