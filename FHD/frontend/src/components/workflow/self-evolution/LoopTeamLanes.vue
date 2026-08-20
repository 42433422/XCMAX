<script setup lang="ts">
defineProps<{
  lanes: Array<{
    id: string
    stage: string
    source: string
    rosterLabel?: string
    rosterStatus?: string
    dutyRegisteredLabel?: string
    dutyRegistered?: unknown
    department?: string
  }>
}>()
</script>

<template>
  <div class="selp-team" role="list" aria-label="循环参与员工">
    <div class="selp-team-head">
      <span>参与员工泳道</span>
      <strong>{{ lanes.length ? `${lanes.length} 名` : '等待记录回写' }}</strong>
    </div>
    <div v-if="lanes.length" class="selp-team-list">
      <span
        v-for="lane in lanes"
        :key="`${lane.id}-${lane.stage}`"
        class="selp-team-chip"
        :class="{
          'selp-team-chip--outside': lane.rosterStatus === 'out_of_roster' || lane.dutyRegistered === false,
        }"
        role="listitem"
      >
        <strong>{{ lane.id }}</strong>
        <small>{{ lane.stage }} · {{ lane.source }}</small>
        <small v-if="lane.rosterLabel || lane.dutyRegisteredLabel || lane.department"
          >{{ lane.rosterLabel || '排班未知' }}<template v-if="lane.dutyRegisteredLabel"> · {{ lane.dutyRegisteredLabel }}</template
          ><template v-if="lane.department"> · {{ lane.department }}</template></small
        >
      </span>
    </div>
    <p v-else class="selp-team-empty">当前状态数据尚未暴露员工 ID；后端记录一旦写入 employee_id / actor / assignee 会自动显示。</p>
  </div>
</template>

<style scoped>
.selp-team {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.78);
}

.selp-team-head,
.selp-team-list {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.selp-team-head {
  justify-content: space-between;
  color: #334155;
  font-size: 12px;
  font-weight: 900;
}

.selp-team-chip {
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
  max-width: 220px;
  padding: 7px 9px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--selp-accent) 10%, #fff);
  color: #0f172a;
}

.selp-team-chip--outside {
  background: #fef2f2;
  color: #991b1b;
}

.selp-team-chip strong {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-team-chip small,
.selp-team-empty {
  margin: 0;
  color: var(--selp-muted);
  font-size: 11px;
  line-height: 1.35;
}
</style>
