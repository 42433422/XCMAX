<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ApprovalWorkspaceCtx } from './assemble'
import { salesApprovalPreview, getExecutionBadge, getStatusTone, getApplicantLabel } from './awHelpers'
import { useDialogFocus, useDialogScrollLock } from '@/composables/useDialogFocus'

// 右侧详情抽屉：替代居中 Modal，保留列表滚动位置，可连续处理下一条。
const props = defineProps<{ tm: ApprovalWorkspaceCtx }>()

const {
  showDetails, closeDetails, selectedRequest, canApprove, approve, reject, actioningId,
  getBusinessLabel, getStatusLabel, getActionIcon, formatTime, getWorkflowExecutionStatusLabel,
} = props.tm

const panel = ref<HTMLElement | null>(null)
const close = () => { if (!actioningId.value) closeDetails() }
useDialogFocus(panel, () => showDetails.value, close)
useDialogScrollLock(() => showDetails.value)

const salesPreview = computed(() => salesApprovalPreview(selectedRequest.value))
const executionBadge = computed(() => getExecutionBadge(selectedRequest.value?.workflow_execution))
const busy = computed(() => actioningId.value > 0)
</script>

<template>
  <Teleport to="body">
    <div v-if="showDetails" class="approval-drawer-mask" @click.self="close">
      <aside
        ref="panel"
        class="approval-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="审批详情"
        tabindex="-1"
        data-tutorial-id="approval-detail"
      >
        <header class="approval-drawer-head">
          <div class="approval-drawer-title">
            <span class="status-badge" :class="getStatusTone(selectedRequest ? selectedRequest.status : '')">
              {{ selectedRequest ? getStatusLabel(selectedRequest.status) : '' }}
            </span>
            <h3>{{ selectedRequest?.title || '审批详情' }}</h3>
          </div>
          <button type="button" class="drawer-close" aria-label="关闭" @click="close">
            <i class="fa fa-times"></i>
          </button>
        </header>

        <div v-if="selectedRequest" class="approval-drawer-body">
          <div class="detail-section">
            <h4>基本信息</h4>
            <div class="detail-grid">
              <div class="detail-item">
                <label>申请编号</label>
                <span class="mono">{{ selectedRequest.request_no }}</span>
              </div>
              <div class="detail-item">
                <label>业务类型</label>
                <span>{{ salesPreview ? '销售业务' : getBusinessLabel(selectedRequest.business_type) }}</span>
              </div>
              <div class="detail-item">
                <label>发起人</label>
                <span>{{ getApplicantLabel(selectedRequest) }}</span>
              </div>
              <div class="detail-item">
                <label>当前节点</label>
                <span>{{ selectedRequest.current_node_name || '—' }}</span>
              </div>
              <div v-if="!salesPreview" class="detail-item full-width">
                <label>申请描述</label>
                <p>{{ selectedRequest.description || '—' }}</p>
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
                <span class="status-badge" :class="executionBadge?.tone">
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
              <ul v-if="selectedRequest.workflow_execution.node_results?.length" class="workflow-execution-nodes">
                <li v-for="node in selectedRequest.workflow_execution.node_results" :key="node.node_id">
                  <span :class="['workflow-node-status', node.success ? 'ok' : 'fail']">
                    {{ node.success ? '成功' : '失败' }}
                  </span>
                  <span class="workflow-node-main">{{ node.node_id }} · {{ node.tool_id }}.{{ node.action }}</span>
                  <span v-if="node.retries" class="workflow-node-meta">重试 {{ node.retries }} 次</span>
                  <span v-if="node.error" class="workflow-node-error">{{ node.error }}</span>
                  <span v-if="node.recovery_hint" class="workflow-node-hint">恢复建议：{{ node.recovery_hint }}</span>
                </li>
              </ul>
            </div>
          </div>

          <div v-if="salesPreview" class="detail-section">
            <h4>{{ salesPreview.operation }}参数</h4>
            <p class="detail-customer">客户：{{ salesPreview.customer }}</p>
            <table class="detail-table">
              <thead><tr><th>商品</th><th>型号</th><th>数量</th><th>单价</th></tr></thead>
              <tbody><tr v-for="(item, index) in salesPreview.items" :key="index">
                <td>{{ item.product_name || item.product_id || '未填写' }}</td>
                <td>{{ item.model_number || '未填写' }}</td>
                <td>{{ item.quantity ?? '未填写' }}</td><td>{{ item.unit_price ?? '未填写' }}</td>
              </tr></tbody>
            </table>
            <p data-testid="sales-approval-total">
              总金额（参数合计）：{{ salesPreview.amount ?? '金额待确认' }} {{ salesPreview.amount ? salesPreview.currency : '' }}
            </p>
            <details><summary>原始参数</summary><pre>{{ selectedRequest.description }}</pre></details>
          </div>

          <div class="detail-section">
            <h4>审批记录</h4>
            <div v-if="selectedRequest.records?.length" class="timeline">
              <div v-for="record in selectedRequest.records" :key="record.id" class="timeline-item">
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
            <p v-else class="detail-empty">暂无审批记录</p>
          </div>
        </div>

        <footer class="approval-drawer-foot">
          <button class="btn btn-ghost" @click="close">关闭</button>
          <template v-if="canApprove && selectedRequest">
            <button class="btn btn-reject" :disabled="busy" @click="reject(selectedRequest.id)">
              <i class="fa fa-times"></i> 拒绝
            </button>
            <button
              class="btn btn-approve"
              data-tutorial-id="approval-approve-action"
              :disabled="busy"
              @click="approve(selectedRequest.id, selectedRequest)"
            >
              <i class="fa fa-check"></i> {{ busy ? '提交中…' : '通过' }}
            </button>
          </template>
        </footer>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped src="./approval-workspace.css"></style>
