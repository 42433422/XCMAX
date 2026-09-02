<script setup lang="ts">
import { asArray, firstText, governanceSummaryText, type AnyRecord } from './runtimeHelpers'

// 拆分自 SelfEvolutionLoopRuntimePanel.vue 模板（原 governance audit 区块）；模板逐字迁移，行为不变。
defineProps<{
  governanceAuditRecent: AnyRecord[]
  governanceAuditSummary: AnyRecord
}>()
</script>

<template>
    <div v-if="governanceAuditRecent.length" class="selp-governance-audit" aria-label="最近治理动作">
      <div class="selp-governance-audit-head">
        <span>Governance audit</span>
        <strong>{{ firstText(governanceAuditSummary.health, 'ok') }} · {{ governanceAuditRecent.length }}</strong>
        <small>{{ governanceAuditSummary.success_count ?? 0 }} ok · {{ governanceAuditSummary.failure_count ?? 0 }} failed · consecutive {{ governanceAuditSummary.consecutive_failures ?? 0 }}</small>
      </div>
      <ul>
        <li v-for="item in governanceAuditRecent.slice().reverse().slice(0, 5)" :key="`${item.created_at || item.action}-${item.exit_code ?? ''}`">
          <span>{{ item.action || 'governance' }}</span>
          <strong>{{ item.status || (item.ok === false ? 'failed' : 'success') }}</strong>
          <small>{{ governanceSummaryText(item) }}<template v-if="asArray(item.target_employee_ids).length"> · {{ asArray(item.target_employee_ids).slice(0, 3).join(' / ') }}</template></small>
        </li>
      </ul>
    </div>
</template>

<style scoped src="./self-evolution-loop-runtime.css"></style>
