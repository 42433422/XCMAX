<script setup lang="ts">
// 拆分自 SelfEvolutionLoopRuntimePanel.vue 模板（原参与员工泳道区块）；模板逐字迁移，行为不变。
interface TeamLane {
  id: string
  stage: string
  source: string
  rosterLabel?: string
  rosterStatus?: string
  dutyRegisteredLabel?: string
  dutyRegistered?: unknown
  department?: string
}

defineProps<{
  teamLanes: TeamLane[]
}>()
</script>

<template>
    <div class="selp-team" role="list" aria-label="loop 参与员工">
      <div class="selp-team-head">
        <span>参与员工泳道</span>
        <strong>{{ teamLanes.length ? `${teamLanes.length} 名` : '等待 ledger 回写' }}</strong>
      </div>
      <div v-if="teamLanes.length" class="selp-team-list">
        <span v-for="lane in teamLanes" :key="`${lane.id}-${lane.stage}`" class="selp-team-chip" :class="{ 'selp-team-chip--outside': lane.rosterStatus === 'out_of_roster' || lane.dutyRegistered === false }" role="listitem">
          <strong>{{ lane.id }}</strong>
          <small>{{ lane.stage }} · {{ lane.source }}</small>
          <small v-if="lane.rosterLabel || lane.dutyRegisteredLabel || lane.department">{{ lane.rosterLabel || '编制未知' }}<template v-if="lane.dutyRegisteredLabel"> · {{ lane.dutyRegisteredLabel }}</template><template v-if="lane.department"> · {{ lane.department }}</template></small>
        </span>
      </div>
      <p v-else class="selp-team-empty">
        当前 status payload 尚未暴露员工 ID；后端 ledger 一旦写入 employee_id / actor / assignee 会自动显示。
      </p>
    </div>
</template>

<style scoped src="./self-evolution-loop-runtime.css"></style>
