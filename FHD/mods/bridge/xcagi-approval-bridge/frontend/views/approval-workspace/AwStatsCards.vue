<script setup lang="ts">
import type { ApprovalWorkspaceCtx } from './assemble'

// 统计卡即筛选器：点击后切换到对应分组并高亮当前筛选。
const props = defineProps<{ tm: ApprovalWorkspaceCtx }>()
const { stats, activeTab, initiatedFilter, applyStatsFilter } = props.tm

const cards = [
  { key: 'pending', label: '待审批', icon: 'fa-clock-o' },
  { key: 'initiated', label: '我发起的', icon: 'fa-paper-plane' },
  { key: 'approved', label: '已通过', icon: 'fa-check-circle' },
  { key: 'rejected', label: '已拒绝', icon: 'fa-times-circle' },
] as const

const isActive = (key: typeof cards[number]['key']) =>
  key === 'pending'
    ? activeTab.value === 'pending' && initiatedFilter.value === 'all'
    : key === 'initiated'
      ? activeTab.value === 'initiated' && initiatedFilter.value === 'all'
      : activeTab.value === 'initiated' && initiatedFilter.value === key
</script>

<template>
  <div class="stats-cards" role="group" aria-label="审批筛选">
    <button
      v-for="card in cards"
      :key="card.key"
      type="button"
      class="stat-card"
      :class="[card.key, { active: isActive(card.key) }]"
      :aria-pressed="isActive(card.key)"
      @click="applyStatsFilter(card.key)"
    >
      <span class="stat-icon"><i class="fa" :class="card.icon"></i></span>
      <span class="stat-info">
        <span class="stat-value">{{ stats[card.key] }}</span>
        <span class="stat-label">{{ card.label }}</span>
      </span>
    </button>
  </div>
</template>

<style scoped src="./approval-workspace.css"></style>
