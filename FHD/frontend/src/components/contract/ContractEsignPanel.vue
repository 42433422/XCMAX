<template>
  <div class="contract-esign-stub muted">电子签面板仅在企业运维/客服场景可用。</div>
</template>

<script setup lang="ts">
defineProps<{
  marketUserId?: number
  username?: string
  partyA?: string
  compact?: boolean
}>()
defineEmits<{ updated: [doc: Record<string, unknown>] }>()
</script>

<style scoped>
.contract-esign-stub {
  font-size: 13px;
  padding: 8px 0;
}
</style>
