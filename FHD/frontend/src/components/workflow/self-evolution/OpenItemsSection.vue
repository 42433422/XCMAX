<script setup lang="ts">
import { asArray, asRecord, type AnyRecord } from '@/composables/useLoopRuntimePanel'

defineProps<{
  items: AnyRecord[]
}>()
</script>

<template>
  <div v-if="items.length" class="selp-open-items" aria-label="待处理审批与记忆项">
    <div v-for="item in items" :key="`${item.kind || 'item'}-${item.run_id || item.created_at}`" class="selp-open-item">
      <div>
        <span>{{ item.kind || '待处理项' }}</span>
        <strong>{{ item.reason || '待处理' }}</strong>
        <small>
          <template v-if="item.run_id">运行 {{ item.run_id }}</template>
          <template v-if="item.task_id"> · 任务 {{ item.task_id }}</template>
          <template v-if="item.created_at"> · {{ item.created_at }}</template>
        </small>
      </div>
      <small v-if="asRecord(item.roster_gate).action || asRecord(item.roster_gate).reason" class="selp-open-item-gate">
        排班 {{ asRecord(item.roster_gate).action || '检查' }} · {{ asRecord(item.roster_gate).reason || '策略' }}
      </small>
      <small v-if="asArray(asRecord(item.active_gates).blocking_keys).length" class="selp-open-item-gate">
        检查项未通过 · {{ asArray(asRecord(item.active_gates).blocking_keys).join(' / ') }}
      </small>
      <small v-if="asRecord(item.governance_gate).action || asRecord(item.governance_gate).reason" class="selp-open-item-gate">
        管理 {{ asRecord(item.governance_gate).action || '检查' }} · {{ asRecord(item.governance_gate).reason || '策略' }}
      </small>
      <small v-if="asRecord(item.evolution_gate).pause === true || asRecord(item.evolution_gate).reason" class="selp-open-item-gate">
        进化 {{ asRecord(item.evolution_gate).pause === true ? '暂停' : '允许' }} · {{ asRecord(item.evolution_gate).reason || '指标策略' }}
      </small>
      <small v-if="asArray(asRecord(item.roster_gate).out_of_roster_ids).length" class="selp-open-item-ids">
        {{ asArray(asRecord(item.roster_gate).out_of_roster_ids).slice(0, 4).join(' / ') }}
      </small>
      <small v-if="asArray(asRecord(item.roster_gate).not_deployed_ids).length" class="selp-open-item-ids">
        未登记上岗：{{ asArray(asRecord(item.roster_gate).not_deployed_ids).slice(0, 4).join(' / ') }}
      </small>
    </div>
  </div>
</template>

<style scoped>
.selp-open-items {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 10px 11px;
  border: 1px solid #fed7aa;
  border-radius: 12px;
  background: #fffbeb;
}

.selp-open-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  min-width: 0;
}

.selp-open-item div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.selp-open-item span,
.selp-open-item small {
  overflow: hidden;
  color: #92400e;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-open-item strong {
  overflow: hidden;
  color: #78350f;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-open-item-gate {
  max-width: 260px;
  padding: 4px 8px;
  border-radius: 999px;
  background: #fee2e2;
  color: #991b1b !important;
  font-weight: 900;
}

.selp-open-item-ids {
  grid-column: 1 / -1;
  padding: 5px 7px;
  border-radius: 8px;
  background: rgba(153, 27, 27, 0.08);
  color: #991b1b !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 800;
}
</style>