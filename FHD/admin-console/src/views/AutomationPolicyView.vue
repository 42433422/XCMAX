<template>
  <div class="xcmax-admin-view" id="view-automation-policy">
    <div class="page-content">
      <AutomationPolicyPanel />
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'AutomationPolicyView' }
</script>

<script setup lang="ts">
import AutomationPolicyPanel from '@/components/admin/AutomationPolicyPanel.vue'
</script>

<style scoped>
.xcmax-admin-view .page-content {
  padding: 16px 20px 24px;
}
</style>
