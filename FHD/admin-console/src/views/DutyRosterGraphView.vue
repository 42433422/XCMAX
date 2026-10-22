<template>
  <div class="duty-roster-graph-view" id="view-duty-roster-graph">
    <DutyRosterGraphPanel variant="page" :open="true" />
  </div>
</template>

<script lang="ts">
export default { name: 'DutyRosterGraphView' }
</script>

<script setup lang="ts">
import DutyRosterGraphPanel from '../components/workflow/DutyRosterGraphPanel.vue'
</script>

<style scoped>
.duty-roster-graph-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  background: var(--bg-color, #edf3fa);
}
</style>
