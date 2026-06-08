<template>
  <div class="duty-roster-graph-view" id="view-duty-roster-graph">
    <DutyRosterGraphPanel variant="page" :open="true" />
  </div>
</template>

<script lang="ts">
export default { name: 'DutyRosterGraphView' }
</script>

<script setup lang="ts">
import DutyRosterGraphPanel from '@/components/workflow/DutyRosterGraphPanel.vue'
</script>

<style scoped>
.duty-roster-graph-view {
  min-height: 100vh;
  background: #0b1220;
}
</style>
