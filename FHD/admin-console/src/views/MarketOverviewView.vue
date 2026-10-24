<template>
  <div class="xcmax-admin-view" id="view-market-overview">
    <div class="page-content">
      <MarketOverviewPanel />
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'MarketOverviewView' }
</script>

<script setup lang="ts">
import MarketOverviewPanel from '@/components/admin/MarketOverviewPanel.vue'
</script>

<style scoped>
.xcmax-admin-view .page-content {
  padding: 16px 20px 24px;
}
</style>
