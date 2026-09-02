<script setup lang="ts">
import type { ApprovalWorkspaceCtx } from './assemble'

// 拆分自 ApprovalWorkspaceView.vue 模板（原第 8–46 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: ApprovalWorkspaceCtx }>()

const { stats } = props.tm
</script>

<template>
    <!-- 统计卡片 -->
    <div class="stats-cards">
      <div class="stat-card pending">
        <div class="stat-icon">
          <i class="fa fa-clock-o"></i>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.pending }}</div>
          <div class="stat-label">待审批</div>
        </div>
      </div>
      <div class="stat-card initiated">
        <div class="stat-icon">
          <i class="fa fa-paper-plane"></i>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.initiated }}</div>
          <div class="stat-label">我发起的</div>
        </div>
      </div>
      <div class="stat-card approved">
        <div class="stat-icon">
          <i class="fa fa-check-circle"></i>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.approved }}</div>
          <div class="stat-label">已通过</div>
        </div>
      </div>
      <div class="stat-card rejected">
        <div class="stat-icon">
          <i class="fa fa-times-circle"></i>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.rejected }}</div>
          <div class="stat-label">已拒绝</div>
        </div>
      </div>
    </div>
</template>

<style scoped src="./approval-workspace.css"></style>
