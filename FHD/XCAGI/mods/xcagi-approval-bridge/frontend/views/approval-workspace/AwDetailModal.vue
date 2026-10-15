<script setup lang="ts">
import Modal from '@/components/Modal.vue'
import { computed } from 'vue'
import type { ApprovalWorkspaceCtx } from './assemble'
import { salesApprovalPreview } from './awHelpers'

const props = defineProps<{ tm: ApprovalWorkspaceCtx }>()

const {
  showDetails, closeDetails, selectedRequest, canApprove, approve, reject,
  getBusinessLabel, getStatusLabel, getActionIcon, formatTime, getWorkflowExecutionStatusLabel,
} = props.tm
const salesPreview = computed(() => salesApprovalPreview(selectedRequest.value))
</script>

<template>
    <!-- 审批详情弹窗（复用宿主 Modal 原语） -->
    <Modal
      :model-value="showDetails"
      title="审批详情"
      max-width="800px"
      @close="closeDetails"
    >
      <div v-if="selectedRequest" class="request-detail" data-tutorial-id="approval-detail">
        <div class="detail-section">
          <h4>基本信息</h4>
          <div class="detail-grid">
            <div class="detail-item">
              <label>申请编号：</label>
              <span>{{ selectedRequest.request_no }}</span>
            </div>
            <div class="detail-item">
              <label>审批标题：</label>
              <span>{{ salesPreview?.operation ?? selectedRequest.title }}</span>
            </div>
            <div class="detail-item">
              <label>业务类型：</label>
              <span>{{ salesPreview ? '销售业务' : getBusinessLabel(selectedRequest.business_type) }}</span>
            </div>
            <div class="detail-item">
              <label>当前状态：</label>
              <span class="status-tag" :class="selectedRequest.status">
                {{ getStatusLabel(selectedRequest.status) }}
              </span>
            </div>
            <div v-if="!salesPreview" class="detail-item full-width">
              <label>申请描述：</label>
              <p>{{ selectedRequest.description }}</p>
            </div>
          </div>
        </div>

        <div v-if="salesPreview" class="detail-section">
          <h4>{{ salesPreview.operation }}参数</h4>
          <p>客户：{{ salesPreview.customer }}</p>
          <table>
            <thead><tr><th>商品</th><th>型号</th><th>数量</th><th>单价</th></tr></thead>
            <tbody><tr v-for="(item, index) in salesPreview.items" :key="index">
              <td>{{ item.product_name || item.product_id || '未填写' }}</td>
              <td>{{ item.model_number || '未填写' }}</td>
              <td>{{ item.quantity ?? '未填写' }}</td><td>{{ item.unit_price ?? '未填写' }}</td>
            </tr></tbody>
          </table>
          <p data-testid="sales-approval-total">总金额（参数合计）：{{ salesPreview.amount ?? '金额待确认' }} {{ salesPreview.amount ? salesPreview.currency : '' }}</p>
          <details><summary>原始参数</summary><pre>{{ selectedRequest.description }}</pre></details>
        </div>

        <div class="detail-section">
          <h4>审批记录</h4>
          <div class="timeline">
            <div
              v-for="record in selectedRequest.records"
              :key="record.id"
              class="timeline-item"
            >
              <div class="timeline-dot" :class="record.action">
                <i :class="getActionIcon(record.action)"></i>
              </div>
              <div class="timeline-content">
                <div class="timeline-header">
                  <span class="node-name">{{ record.node_name }}</span>
                  <span class="time">{{ formatTime(record.created_at) }}</span>
                </div>
                <div class="timeline-body">
                  <div class="approver">审批人：{{ record.approver_name || record.approver_id || '系统' }}</div>
                  <div class="opinion">{{ record.opinion }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="selectedRequest.workflow_execution" class="detail-section">
          <h4>AI 工作流执行</h4>
          <div
            class="workflow-execution-panel"
            :class="{ failed: selectedRequest.workflow_execution.success === false }"
          >
            <div class="workflow-execution-head">
              <span class="workflow-execution-status">
                {{ getWorkflowExecutionStatusLabel(selectedRequest.workflow_execution) }}
              </span>
              <span v-if="selectedRequest.workflow_execution.plan_id" class="workflow-execution-plan">
                {{ selectedRequest.workflow_execution.plan_id }}
              </span>
            </div>
            <div class="workflow-execution-meta">
              <span v-if="selectedRequest.workflow_execution.intent">
                意图：{{ selectedRequest.workflow_execution.intent }}
              </span>
              <span>
                节点：{{ selectedRequest.workflow_execution.nodes_executed || 0 }}/{{ selectedRequest.workflow_execution.nodes_total || 0 }}
              </span>
            </div>
            <div v-if="selectedRequest.workflow_execution.message" class="workflow-execution-message">
              {{ selectedRequest.workflow_execution.message }}
            </div>
            <ul
              v-if="selectedRequest.workflow_execution.node_results?.length"
              class="workflow-execution-nodes"
            >
              <li
                v-for="node in selectedRequest.workflow_execution.node_results"
                :key="node.node_id"
              >
                <span :class="['workflow-node-status', node.success ? 'ok' : 'fail']">
                  {{ node.success ? '成功' : '失败' }}
                </span>
                <span class="workflow-node-main">
                  {{ node.node_id }} · {{ node.tool_id }}.{{ node.action }}
                </span>
                <span v-if="node.retries" class="workflow-node-meta">
                  重试 {{ node.retries }} 次
                </span>
                <span v-if="node.error" class="workflow-node-error">{{ node.error }}</span>
                <span v-if="node.recovery_hint" class="workflow-node-hint">
                  恢复建议：{{ node.recovery_hint }}
                </span>
              </li>
            </ul>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-link" @click="closeDetails">
          <i class="fa fa-times"></i> 关闭
        </button>
        <button v-if="canApprove && selectedRequest" class="btn btn-reject" @click="reject(selectedRequest.id)">
          <i class="fa fa-times"></i> 拒绝
        </button>
        <button v-if="canApprove && selectedRequest" class="btn btn-approve" data-tutorial-id="approval-approve-action" @click="approve(selectedRequest.id)">
          <i class="fa fa-check"></i> 通过
        </button>
      </template>
    </Modal>
</template>

<style scoped src="./approval-workspace.css"></style>
