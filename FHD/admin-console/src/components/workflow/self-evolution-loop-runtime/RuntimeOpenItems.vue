<script setup lang="ts">
import { asArray, asRecord, type AnyRecord } from './runtimeHelpers'

// 拆分自 SelfEvolutionLoopRuntimePanel.vue 模板（原 open items 区块）；模板逐字迁移，行为不变。
defineProps<{
  openApprovalItems: AnyRecord[]
}>()
</script>

<template>
    <div v-if="openApprovalItems.length" class="selp-open-items" aria-label="待处理审批与记忆项">
      <div v-for="item in openApprovalItems" :key="`${item.kind || 'item'}-${item.run_id || item.created_at}`" class="selp-open-item">
        <div>
          <span>{{ item.kind || 'open item' }}</span>
          <strong>{{ item.reason || 'pending' }}</strong>
          <small>
            <template v-if="item.run_id">run {{ item.run_id }}</template>
            <template v-if="item.task_id"> · task {{ item.task_id }}</template>
            <template v-if="item.created_at"> · {{ item.created_at }}</template>
          </small>
        </div>
        <small v-if="asRecord(item.roster_gate).action || asRecord(item.roster_gate).reason" class="selp-open-item-gate">
          roster {{ asRecord(item.roster_gate).action || 'gate' }} · {{ asRecord(item.roster_gate).reason || 'policy' }}
        </small>
        <small v-if="asArray(asRecord(item.active_gates).blocking_keys).length" class="selp-open-item-gate">
          active gates blocked · {{ asArray(asRecord(item.active_gates).blocking_keys).join(' / ') }}
        </small>
        <small v-if="asRecord(item.governance_gate).action || asRecord(item.governance_gate).reason" class="selp-open-item-gate">
          governance {{ asRecord(item.governance_gate).action || 'gate' }} · {{ asRecord(item.governance_gate).reason || 'policy' }}
        </small>
        <small v-if="asRecord(item.evolution_gate).pause === true || asRecord(item.evolution_gate).reason" class="selp-open-item-gate">
          evolution {{ asRecord(item.evolution_gate).pause === true ? 'pause' : 'allow' }} · {{ asRecord(item.evolution_gate).reason || 'metrics policy' }}
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

<style scoped src="./self-evolution-loop-runtime.css"></style>
