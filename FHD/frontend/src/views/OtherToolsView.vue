<template>
  <DutyRosterGraphView v-if="isAdminConsoleSpa()" />
  <HostModBridgeView
    v-else
    mod-id="xcagi-office-employee-pack-bridge"
    view="OtherToolsView"
    title="员工视图"
  />
</template>

<script setup lang="ts">
import { defineAsyncComponent } from 'vue'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import HostModBridgeView from '@/components/HostModBridgeView.vue'

const DutyRosterGraphView = defineAsyncComponent(
  () => import('@admin-console-inject/views/DutyRosterGraphView.vue'),
)
</script>
