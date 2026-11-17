<template>
  <EmployeeWorkspaceLoopConsole v-if="isAdmin" initial-pane="flow" />
  <HostModBridgeView v-else mod-id="xcagi-workflow-visualization-bridge" view="WorkflowVisualizationView" title="流程可视化" />
</template>

<script setup lang="ts">
import HostModBridgeView from '@/components/HostModBridgeView.vue'
import EmployeeWorkspaceLoopConsole from '@admin-console-inject/employeeWorkspace/EmployeeWorkspaceLoopConsole.vue'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
const isAdmin = isAdminConsoleSpa()
</script>
