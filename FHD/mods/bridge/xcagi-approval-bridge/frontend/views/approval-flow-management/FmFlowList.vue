<script setup lang="ts">
import type { ApprovalFlowManagementCtx } from './assemble'

// 拆分自 ApprovalFlowManagementView.vue 模板（原第 8–63 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: ApprovalFlowManagementCtx }>()

const {
  flowList, editFlow, toggleFlowStatus, deleteFlow, getBusinessTypeLabel, showCreateModal,
} = props.tm
</script>

<template>
    <!-- 流程列表 -->
    <div class="flow-list-section">
      <div class="section-header">
        <h3>审批流程列表</h3>
        <button class="btn btn-primary" @click="showCreateModal = true">
          <i class="fa fa-plus"></i> 新建流程
        </button>
      </div>
      <div class="flow-list">
        <div
          v-for="flow in flowList"
          :key="flow.id"
          class="flow-item"
          @click="editFlow(flow)"
        >
          <div class="flow-info">
            <div class="flow-header">
              <h4>{{ flow.flow_name }}</h4>
              <span class="flow-status" :class="{ active: flow.is_active }">
                {{ flow.is_active ? '启用' : '禁用' }}
              </span>
            </div>
            <div class="flow-meta">
              <span class="flow-key">KEY: {{ flow.flow_key }}</span>
              <span class="flow-type">{{ getBusinessTypeLabel(flow.business_type) }}</span>
            </div>
            <div class="flow-nodes">
              <span class="node-badge" v-for="(node, idx) in flow.nodes" :key="node.id">
                {{ idx + 1 }}. {{ node.node_name }}
              </span>
            </div>
            <div class="flow-description">{{ flow.description || '暂无描述' }}</div>
          </div>
          <div class="flow-actions">
            <button
              class="btn-icon"
              @click.stop="toggleFlowStatus(flow)"
              :title="flow.is_active ? '禁用' : '启用'"
            >
              <i :class="flow.is_active ? 'fa fa-pause' : 'fa fa-play'"></i>
            </button>
            <button
              class="btn-icon"
              @click.stop="deleteFlow(flow.id)"
              title="删除"
            >
              <i class="fa fa-trash"></i>
            </button>
          </div>
        </div>
        <div v-if="flowList.length === 0" class="empty-state">
          <i class="fa fa-folder-open-o"></i>
          <p>暂无审批流程，点击"新建流程"创建第一个</p>
        </div>
      </div>
    </div>
</template>

<style scoped src="./approval-flow-management.css"></style>
