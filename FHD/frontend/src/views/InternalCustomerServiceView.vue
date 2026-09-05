<template>
  <div class="customer-service-page">
    <SharedIssueAcceptancePanel />
    <HostModBridgeView mod-id="xcagi-customer-service-bridge" view="InternalCustomerServiceView" title="客服" />
  </div>
</template>

<script setup lang="ts">
import HostModBridgeView from '@/components/HostModBridgeView.vue'
import SharedIssueAcceptancePanel from '@/components/SharedIssueAcceptancePanel.vue'
</script>

<style scoped>
.customer-service-page { display: flex; flex-direction: column; flex: 1; min-height: 0; }
</style>
