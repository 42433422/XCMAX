<template>
  <div class="xcmax-admin-view admin-screen" id="view-duty-time-architecture">
    <div class="page-content">
      <div class="page-header">
        <div>
          <h2>同时完成时间架构</h2>
        </div>
      </div>
      <XcmaxDashboardEmbed :src="embedUrl" title="同时完成时间架构" />
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'DutyTimeArchitectureView' }
</script>

<script setup lang="ts">
import XcmaxDashboardEmbed from '@/components/admin/XcmaxDashboardEmbed.vue'
import { xcmaxDutyTimeArchitectureEmbedUrl } from '@/constants/xcmaxDashboardEmbed'

const embedUrl = xcmaxDutyTimeArchitectureEmbedUrl()
</script>

<style scoped>
.xcmax-admin-view .page-content {
  padding: 16px 20px 24px;
}
.page-header h2 {
  margin: 0;
  font-size: 20px;
}
</style>
