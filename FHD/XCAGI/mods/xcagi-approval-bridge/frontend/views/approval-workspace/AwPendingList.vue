<script setup lang="ts">
import type { ApprovalWorkspaceCtx } from './assemble'

// 拆分自 ApprovalWorkspaceView.vue 模板（原第 48–95 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: ApprovalWorkspaceCtx }>()

const {
  pendingRequests, viewDetails, approve, reject, viewAll,
  getBusinessIcon, formatTime,
} = props.tm
</script>

<template>
    <!-- 待审批列表 -->
    <div class="section">
      <div class="section-header">
        <h3>待我审批</h3>
        <button class="btn-link" @click="viewAll('pending')">查看全部</button>
      </div>
      <div class="request-list" data-tutorial-id="approval-pending-list">
        <div
          v-for="item in pendingRequests"
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
                <span class="request-no">{{ item.request_no }}</span>
                <span class="request-time">{{ formatTime(item.created_at) }}</span>
              </div>
            </div>
          </div>
          <div class="request-actions">
            <button
              class="btn-approve"
              @click.stop="approve(item.id)"
              title="通过"
            >
              <i class="fa fa-check"></i>
            </button>
            <button
              class="btn-reject"
              @click.stop="reject(item.id)"
              title="拒绝"
            >
              <i class="fa fa-times"></i>
            </button>
          </div>
        </div>
        <div v-if="pendingRequests.length === 0" class="empty-state">
          <i class="fa fa-check-circle-o"></i>
          <p>暂无待审批事项</p>
        </div>
      </div>
    </div>
</template>

<style scoped src="./approval-workspace.css"></style>
