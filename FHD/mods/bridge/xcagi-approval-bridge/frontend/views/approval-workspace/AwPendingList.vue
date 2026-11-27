<script setup lang="ts">
import type { ApprovalWorkspaceCtx } from './assemble'

const props = defineProps<{ tm: ApprovalWorkspaceCtx }>()

const {
  visiblePendingRequests: pendingRequests, viewDetails, approve, reject,
  getBusinessIcon, getBusinessLabel, formatRequestTitle, formatTime,
} = props.tm
</script>

<template>
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
          <button type="button" class="request-title" :title="item.title" @click.stop="viewDetails(item.id)">
            {{ formatRequestTitle(item) }}
          </button>
          <div class="request-meta">
            <span class="request-status pending">待审批</span>
            <span class="request-type">{{ getBusinessLabel(item.business_type) }}</span>
            <span class="request-no">{{ item.request_no }}</span>
            <span class="request-time">{{ formatTime(item.created_at) }}</span>
          </div>
        </div>
      </div>
      <div class="request-actions">
        <button
          class="btn-approve"
          type="button"
          @click.stop="approve(item.id)"
          title="通过"
          aria-label="通过"
        >
          <i class="fa fa-check"></i>
        </button>
        <button
          class="btn-reject"
          type="button"
          @click.stop="reject(item.id)"
          title="拒绝"
          aria-label="拒绝"
        >
          <i class="fa fa-times"></i>
        </button>
        <i class="fa fa-angle-right row-chevron"></i>
      </div>
    </div>
    <div v-if="pendingRequests.length === 0" class="empty-state">
      <i class="fa fa-check-circle-o" aria-hidden="true"></i>
      <p>暂无待审批事项</p>
    </div>
  </div>
</template>

<style scoped src="./approval-workspace.css"></style>
