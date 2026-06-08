<template>
  <section class="workbench-panel employee-ai-panel">
    <WorkbenchShell embedded initial-target="employee" />
  </section>
</template>

<script setup lang="ts">
import WorkbenchShell from '../../views/workbench/WorkbenchShell.vue'
</script>

<style scoped>
.workbench-panel {
  min-height: 0;
}

.employee-ai-panel {
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
  padding: 0.75rem;
  background: #050505;
}

html[data-workbench-theme='light'] .employee-ai-panel {
  background: #f5f5f7;
}
</style>
