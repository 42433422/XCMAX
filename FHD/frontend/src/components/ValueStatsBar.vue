<template>
  <div class="value-stats-bar" role="status" aria-live="polite">
    <i class="fa fa-trophy value-stats-bar__icon" aria-hidden="true"></i>
    <span class="value-stats-bar__text">
      已为您解决 <strong class="value-stats-bar__num">{{ countText }}</strong> 次任务
      <span class="value-stats-bar__sep" aria-hidden="true">·</span>
      预计节约人工费用 <strong class="value-stats-bar__num">{{ costText }}</strong>
    </span>
  </div>
</template>

<script setup>
/**
 * 工作区底部价值展示条：真实已完成任务数（/api/agent/task-runtime）+ 每单 1.9–5.8 元伪随机折算人工费用。
 * 口径见 constants/valueStats.ts；接口失败静默降级为「—」，绝不阻塞界面。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import agentRunsApi from '@/api/agentRuns'
import { estimateLaborCostSavedCny, formatCny, VALUE_STATS_REFRESH_MS } from '@/constants/valueStats'

const completedCount = ref(null)
let refreshTimer = null

const countText = computed(() => (completedCount.value === null ? '—' : String(completedCount.value)))
const costText = computed(() => (completedCount.value === null ? '—' : formatCny(estimateLaborCostSavedCny(completedCount.value))))

async function load() {
  try {
    const response = await agentRunsApi.getTaskRuntime()
    const raw = response?.data?.progress?.completed_count
    const count = Math.floor(Number(raw))
    completedCount.value = Number.isFinite(count) && count >= 0 ? count : 0
  } catch {
    completedCount.value = null
  }
}

onMounted(() => {
  void load()
  if (typeof window !== 'undefined') {
    refreshTimer = window.setInterval(() => void load(), VALUE_STATS_REFRESH_MS)
  }
})

onBeforeUnmount(() => {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped>
/* 挂载点：聊天页顶部快捷按钮行（ChatQuickActions）最右，行内顶置胶囊。对齐方式由宿主控制。 */
.value-stats-bar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 30px;
  padding: 4px 12px;
  box-sizing: border-box;
  border: 1px solid rgba(203, 213, 225, 0.7);
  border-radius: 999px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(241, 245, 249, 0.92));
  font-size: 12px;
  color: rgba(71, 85, 105, 0.92);
  user-select: none;
  white-space: nowrap;
}

.value-stats-bar__icon {
  font-size: 12px;
  color: #d97706;
}

.value-stats-bar__num {
  color: #0b72d9;
  font-weight: 700;
  font-size: 13px;
}

.value-stats-bar__sep {
  margin: 0 6px;
  color: rgba(148, 163, 184, 0.8);
}
</style>
