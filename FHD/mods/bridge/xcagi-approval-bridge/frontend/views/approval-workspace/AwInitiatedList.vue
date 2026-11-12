<script setup lang="ts">
import type { ApprovalWorkspaceCtx } from './assemble'

// 拆分自 ApprovalWorkspaceView.vue 模板（原第 97–156 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: ApprovalWorkspaceCtx }>()

const {
  initiatedRequests, viewDetails, deleteSingle, viewAll,
  cleanupLoading, completedInitiatedCount, cleanupCompleted,
  isFinalStatus, getBusinessIcon, getStatusLabel, formatTime,
} = props.tm
</script>

<template>
    <!-- 我发起的列表 -->
    <div class="section">
      <div class="section-header">
        <h3>我发起的</h3>
        <div class="section-actions">
          <button
            class="btn-link btn-cleanup"
            :disabled="cleanupLoading || completedInitiatedCount === 0"
            :title="completedInitiatedCount === 0 ? '暂无可清理的已完成记录' : `清理 ${completedInitiatedCount} 条已完成记录`"
            @click="cleanupCompleted"
          >
            <i class="fa" :class="cleanupLoading ? 'fa-spinner fa-spin' : 'fa-trash-o'"></i>
            清理
            <span v-if="completedInitiatedCount > 0" class="count-badge">{{ completedInitiatedCount }}</span>
          </button>
          <button class="btn-link" @click="viewAll('initiated')">查看全部</button>
        </div>
      </div>
      <div class="request-list" data-tutorial-id="approval-initiated-list">
        <div
          v-for="item in initiatedRequests"
          :key="item.id"
          class="request-item"
          @click="viewDetails(item.id)"
        >
          <div class="request-left">
            <div class="request-icon">
              <i :class="getBusinessIcon(item.business_type)"></i>
            </div>
            <div class="request-info">
              <div class="request-title">{{ item.title }}</div>
              <div class="request-meta">
                <span class="request-status" :class="item.status">
                  {{ getStatusLabel(item.status) }}
                </span>
                <span class="request-time">{{ formatTime(item.created_at) }}</span>
              </div>
            </div>
          </div>
          <div class="request-right">
            <div class="request-current-node" v-if="item.current_node_name">
              <i class="fa fa-map-marker"></i>
              {{ item.current_node_name }}
            </div>
            <button
              v-if="isFinalStatus(item.status)"
              class="btn-delete"
              title="删除此条记录"
              @click.stop="deleteSingle(item)"
            >
              <i class="fa fa-trash-o"></i>
            </button>
          </div>
        </div>
        <div v-if="initiatedRequests.length === 0" class="empty-state">
          <i class="fa fa-paper-plane-o"></i>
          <p>暂无发起的审批</p>
        </div>
      </div>
    </div>
</template>

<style scoped src="./approval-workspace.css"></style>
