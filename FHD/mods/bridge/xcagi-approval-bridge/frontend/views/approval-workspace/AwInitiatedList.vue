<script setup lang="ts">
import type { ApprovalWorkspaceCtx } from './assemble'

const props = defineProps<{ tm: ApprovalWorkspaceCtx; emptyLabel: string }>()

const {
  visibleInitiatedRequests: initiatedRequests, viewDetails, deleteSingle,
  isFinalStatus, getBusinessIcon, getBusinessLabel, getStatusLabel, formatRequestTitle, formatTime,
} = props.tm
</script>

<template>
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
          <button type="button" class="request-title" :title="item.title" @click.stop="viewDetails(item.id)">
            {{ formatRequestTitle(item) }}
          </button>
          <div class="request-meta">
            <span class="request-status" :class="item.status">
              {{ getStatusLabel(item.status) }}
            </span>
            <span class="request-type">{{ getBusinessLabel(item.business_type) }}</span>
            <span class="request-time">{{ formatTime(item.created_at) }}</span>
          </div>
        </div>
      </div>
      <div class="request-right">
        <div class="request-current-node" v-if="item.current_node_name">
          <i class="fa fa-map-marker"></i>
          当前节点：{{ item.current_node_name }}
        </div>
        <button
          v-if="isFinalStatus(item.status)"
          class="btn-delete"
          type="button"
          title="删除此条记录"
          aria-label="删除此条记录"
          @click.stop="deleteSingle(item)"
        >
          <i class="fa fa-trash-o"></i>
        </button>
        <i class="fa fa-angle-right row-chevron"></i>
      </div>
    </div>
    <div v-if="initiatedRequests.length === 0" class="empty-state">
      <i class="fa fa-paper-plane-o" aria-hidden="true"></i>
      <p>{{ emptyLabel }}</p>
    </div>
  </div>
</template>

<style scoped src="./approval-workspace.css"></style>
