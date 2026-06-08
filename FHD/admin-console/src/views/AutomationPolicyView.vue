<template>
  <div class="xcmax-admin-view" id="view-automation-policy">
    <div class="page-content">
      <div class="page-header">
        <a
          class="btn-open-web"
          :href="openUrl"
          target="_blank"
          rel="noopener noreferrer"
        >
          <i class="fa fa-external-link" aria-hidden="true"></i>
          网页打开
        </a>
      </div>
      <XcmaxDashboardEmbed :src="embedUrl" title="自动化方针" />
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'AutomationPolicyView' }
</script>

<script setup lang="ts">
import XcmaxDashboardEmbed from '@/components/admin/XcmaxDashboardEmbed.vue'
import {
  xcmaxAutomationPolicyEmbedUrl,
  xcmaxAutomationPolicyOpenUrl,
} from '@/constants/xcmaxDashboardEmbed'

const embedUrl = xcmaxAutomationPolicyEmbedUrl()
const openUrl = xcmaxAutomationPolicyOpenUrl()
</script>

<style scoped>
.xcmax-admin-view .page-content {
  padding: 16px 20px 24px;
}

.page-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}

.btn-open-web {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid #d9d9d9;
  background: #fff;
  color: #334155;
  font-size: 13px;
  text-decoration: none;
  transition: border-color 0.15s, color 0.15s;
}

.btn-open-web:hover {
  border-color: #1890ff;
  color: #1890ff;
}
</style>
