<template>
  <div class="sync-status-badge" :class="syncClass" :title="badgeTitle" @click="handleClick">
    <i class="fa" :class="iconClass" aria-hidden="true"></i>
    <span>{{ syncLabel }}</span>
    <span v-if="isSyncing" class="sync-spinner" aria-hidden="true"></span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useXCmaxSync } from '@/composables/useXCmaxSync'

const props = withDefaults(defineProps<{
  clickable?: boolean
}>(), { clickable: true })

const { syncStatus, isSyncing, syncLabel, syncClass, syncNow } = useXCmaxSync()

const iconClass = computed(() => {
  if (isSyncing.value) return 'fa-refresh fa-spin'
  if (syncStatus.value.conflictCount > 0) return 'fa-exclamation-triangle'
  if (syncStatus.value.healthy) return 'fa-check-circle'
  if (syncStatus.value.outboxCount > 0) return 'fa-clock-o'
  return 'fa-wifi'
})

const badgeTitle = computed(() => {
  const s = syncStatus.value
  const parts: string[] = []
  if (s.lastSyncAt) parts.push(`最近同步: ${s.lastSyncAt}`)
  if (s.outboxCount) parts.push(`待推送: ${s.outboxCount} 条`)
  if (s.conflictCount) parts.push(`冲突: ${s.conflictCount} 条`)
  if (s.localCursor != null) parts.push(`本地游标: ${s.localCursor}`)
  return parts.join(' · ') || 'XCmax 双向同步'
})

function handleClick() {
  if (!props.clickable || isSyncing.value) return
  syncNow('both')
}
</script>

<style scoped>
.sync-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
  transition: opacity 0.15s, background 0.15s;
  white-space: nowrap;
}

.sync-status-badge:hover { opacity: 0.82; }

.sync-badge--ok      { background: #e6f9f0; color: #10b759; }
.sync-badge--pending { background: #fff7e0; color: #d97706; }
.sync-badge--conflict{ background: #fff1f0; color: #e53e3e; }
.sync-badge--offline { background: #f0f0f0; color: #888; }

.sync-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }
</style>
