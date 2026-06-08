<template>
  <section class="workbench-panel">
    <WorkflowView />
  </section>
</template>

<script setup lang="ts">
import WorkflowView from '../../views/WorkflowView.vue'
</script>

<style scoped>
.workbench-panel {
  min-height: 0;
}
</style>
