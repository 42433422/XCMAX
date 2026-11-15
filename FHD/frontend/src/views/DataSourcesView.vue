<template>
  <div class="data-sources-shell">
    <LocalFileAccessCard />
    <HostModBridgeView mod-id="xcagi-erp-domain-bridge" view="DataSourcesView" title="ERP 业务页" />
  </div>
</template>

<script setup lang="ts">
import HostModBridgeView from '@/components/HostModBridgeView.vue'
import LocalFileAccessCard from '@/components/LocalFileAccessCard.vue'
</script>

<style scoped>
.data-sources-shell { display: flex; flex-direction: column; gap: 16px; padding: 16px; }
</style>
