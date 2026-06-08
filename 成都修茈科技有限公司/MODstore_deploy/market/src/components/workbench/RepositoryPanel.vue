<template>
  <section class="workbench-panel">
    <RepositoryView />
  </section>
</template>

<script setup lang="ts">
import RepositoryView from '../../views/RepositoryView.vue'
</script>

<style scoped>
.workbench-panel {
  min-height: 0;
}
</style>
