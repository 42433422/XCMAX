<template>
  <div class="xcmax-admin-view" id="view-automation-policy">
    <div class="page-content">
      <div class="page-header">
        <div>
          <h2>自动化方针</h2>
          <p class="page-desc">六线独立自动化率 · 全景 loops 轨（XCAGI-Full-Pipeline 嵌入）</p>
        </div>
      </div>
      <XcmaxDashboardEmbed :src="embedUrl" title="自动化方针" />
    </div>
  </div>
</template>

<script>
export default { name: 'AutomationPolicyView' }
</script>

<script setup lang="ts">
import XcmaxDashboardEmbed from '@/components/admin/XcmaxDashboardEmbed.vue'
import { xcmaxAutomationPolicyEmbedUrl } from '@/constants/xcmaxDashboardEmbed'

const embedUrl = xcmaxAutomationPolicyEmbedUrl()
</script>

<style scoped>
@import './XCmaxAdminView.vue';

.page-desc {
  margin: 4px 0 0;
  font-size: 13px;
  color: #64748b;
}
</style>
