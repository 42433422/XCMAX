<script setup>
import { defineProps } from 'vue'

// 拆分自 ApprovalRulesView.vue 模板（原第 88–106 行）；模板逐字迁移，行为不变。
const props = defineProps({ tm: { type: Object, required: true } })

const {
  enabled, pendingApprovals, approveItem, rejectItem, getActionLabel, formatTime,
} = props.tm
</script>

<template>
    <div class="pending-approvals" v-if="enabled && pendingApprovals.length > 0">
      <h3>待审批请求 ({{ pendingApprovals.length }})</h3>
      <div class="pending-list">
        <div class="pending-item" v-for="item in pendingApprovals" :key="item.request_id">
          <div class="pending-info">
            <span class="pending-action">{{ getActionLabel(item.tool_id, item.action) }}</span>
            <span class="pending-time">{{ formatTime(item.created_at) }}</span>
          </div>
          <div class="pending-actions">
            <button class="btn-approve" @click="approveItem(item)">
              <i class="fa fa-check"></i> 通过
            </button>
            <button class="btn-reject" @click="rejectItem(item)">
              <i class="fa fa-times"></i> 拒绝
            </button>
          </div>
        </div>
      </div>
    </div>
</template>

<style scoped src="./approval-rules.css"></style>
