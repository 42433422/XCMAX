<template>
  <div class="data-sources-shell">
    <component :is="compact ? 'details' : 'div'" class="local-file-section">
      <summary v-if="compact">本机文件授权</summary>
      <LocalFileAccessCard />
    </component>
    <HostModBridgeView mod-id="xcagi-erp-domain-bridge" view="DataSourcesView" title="ERP 业务页" />
  </div>
</template>

<script setup lang="ts">
import HostModBridgeView from '@/components/HostModBridgeView.vue'
import LocalFileAccessCard from '@/components/LocalFileAccessCard.vue'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
const compact = isAdminConsoleSpa()
</script>

<style scoped>
.data-sources-shell { display: flex; flex-direction: column; gap: 16px; padding: 16px; }
</style>
