<template>
  <!-- 未知/内部卡片（如 intent）不对客户展示，避免露出调试 JSON -->
  <section v-if="isCustomerFacing" class="cs-card">
    <div class="cs-card__head">
      <span class="cs-card__type">{{ title }}</span>
      <span v-if="status" :class="['cs-card__status', `cs-card__status--${statusKey}`]">{{ statusLabel }}</span>
    </div>

    <div v-if="card.type === 'ticket'" class="cs-grid">
      <div><b>工单号</b><span>{{ card.ticket_no || '—' }}</span></div>
      <div><b>场景</b><span>{{ intentLabel }}</span></div>
      <div><b>对象</b><span>{{ subjectLabel }}</span></div>
      <div><b>状态</b><span>{{ statusText(card.status) }}</span></div>
    </div>

    <div v-else-if="card.type === 'decision'" class="cs-decision">
      <p>{{ card.rationale || '已完成审核判断。' }}</p>
      <div class="cs-grid">
        <div><b>结论</b><span>{{ decisionLabel }}</span></div>
        <div><b>风险</b><span>{{ riskLabel }}</span></div>
        <div><b>置信度</b><span>{{ confidenceText }}</span></div>
      </div>
    </div>

    <div v-else-if="card.type === 'actions'" class="cs-actions">
      <div v-for="item in card.items || []" :key="item.id || item.action_type" class="cs-action-row">
        <span>{{ actionLabel(item.action_type) }}</span>
        <span :class="['cs-card__status', `cs-card__status--${String(item.status || '')}`]">
          {{ statusText(item.status) }}
        </span>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  card: Record<string, any>
}>()

const CUSTOMER_FACING = new Set(['ticket', 'decision', 'actions'])

const isCustomerFacing = computed(() => CUSTOMER_FACING.has(String(props.card?.type || '')))

const title = computed(() => {
  if (props.card.type === 'ticket') return '工单'
  if (props.card.type === 'decision') return '处理结果'
  if (props.card.type === 'actions') return '已处理'
  return ''
})

const intentLabel = computed(() => {
  const map: Record<string, string> = {
    refund: '退款',
    catalog_complaint: '商品投诉',
    catalog_review: '合规审核',
    account_support: '账号权益',
    llm_extension: '模型扩展',
    general: '咨询',
    greeting: '咨询',
  }
  return map[String(props.card.intent || '')] || String(props.card.intent || '咨询')
})

const subjectLabel = computed(() => {
  const typeMap: Record<string, string> = {
    order: '订单',
    catalog_item: '商品',
    account: '账号',
    llm_model: '模型',
    general: '一般咨询',
  }
  const t = String(props.card.subject_type || '')
  const id = String(props.card.subject_id || '').trim()
  const label = typeMap[t] || (t && t !== 'general' ? t : '—')
  return id ? `${label} ${id}` : label
})

const decisionLabel = computed(() => {
  const map: Record<string, string> = {
    approved: '已受理',
    rejected: '未通过',
    needs_more_info: '需补充材料',
  }
  return map[String(props.card.decision || '')] || String(props.card.decision || '—')
})

const riskLabel = computed(() => {
  const map: Record<string, string> = { low: '常规', medium: '中', mid: '中', high: '高' }
  return map[String(props.card.risk_level || '').toLowerCase()] || String(props.card.risk_level || '常规')
})

const status = computed(() => String(props.card.status || props.card.decision || '').trim())
const statusKey = computed(() => status.value.toLowerCase().replace(/\s+/g, '_') || 'pending')
const statusLabel = computed(() => statusText(status.value) || '处理中')
const confidenceText = computed(() => {
  const n = Number(props.card.confidence || 0)
  return n > 0 ? `${Math.round(n * 100)}%` : '—'
})

function statusText(raw: unknown) {
  const s = String(raw || '').toLowerCase()
  const map: Record<string, string> = {
    open: '处理中',
    pending: '处理中',
    processing: '处理中',
    waiting_user: '待补充',
    resolved: '已完成',
    done: '已完成',
    closed: '已完成',
    completed: '已完成',
    approved: '已受理',
    rejected: '未通过',
    failed: '失败',
    skipped: '已跳过',
    needs_more_info: '需补充',
  }
  return map[s] || (raw ? String(raw) : '')
}

function actionLabel(raw: unknown) {
  const s = String(raw || '')
  const map: Record<string, string> = {
    'refund.apply': '申请退款',
    'catalog.complaint.create': '创建投诉',
    'catalog.compliance.review': '合规审核',
    'llm.model_capability.propose': '模型扩展申请',
    'employee.dispatch': '转交处理',
  }
  return map[s] || s || '处理动作'
}
</script>

<style scoped>
.cs-card {
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: #f8fafc;
  border-radius: 14px;
  padding: 14px;
  margin-top: 10px;
  color: #0f172a;
}

.cs-card__head,
.cs-action-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.cs-card__type {
  color: #9a3412;
  font-weight: 800;
  font-size: 13px;
}

.cs-card__status {
  border: 1px solid rgba(22, 163, 74, 0.35);
  border-radius: 999px;
  padding: 4px 9px;
  color: #166534;
  background: rgba(22, 163, 74, 0.12);
  font-size: 12px;
  font-weight: 600;
}

.cs-card__status--failed,
.cs-card__status--rejected {
  color: #b91c1c;
  border-color: rgba(185, 28, 28, 0.35);
  background: rgba(254, 226, 226, 0.9);
}

.cs-card__status--needs_more_info,
.cs-card__status--waiting_user {
  color: #92400e;
  border-color: rgba(217, 119, 6, 0.35);
  background: rgba(254, 243, 199, 0.95);
}

.cs-card__status--resolved,
.cs-card__status--done,
.cs-card__status--closed,
.cs-card__status--completed,
.cs-card__status--approved {
  color: #166534;
  border-color: rgba(22, 163, 74, 0.35);
  background: rgba(220, 252, 231, 0.95);
}

.cs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.cs-grid div {
  display: grid;
  gap: 4px;
}

.cs-grid b {
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}

.cs-grid span,
.cs-decision p,
.cs-action-row {
  color: #0f172a;
  font-size: 13px;
  line-height: 1.45;
  word-break: break-word;
}

.cs-decision p {
  margin: 10px 0 0;
}

.cs-actions {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

/* 深色主题：提高对比，避免发灰发白 */
html:not([data-workbench-theme='light']) .cs-card {
  border-color: rgba(255, 255, 255, 0.16);
  background: rgba(15, 23, 42, 0.72);
  color: #f8fafc;
}

html:not([data-workbench-theme='light']) .cs-card__type {
  color: #fde68a;
}

html:not([data-workbench-theme='light']) .cs-card__status {
  color: #bbf7d0;
  border-color: rgba(74, 222, 128, 0.35);
  background: rgba(22, 163, 74, 0.18);
}

html:not([data-workbench-theme='light']) .cs-grid b {
  color: rgba(226, 232, 240, 0.72);
}

html:not([data-workbench-theme='light']) .cs-grid span,
html:not([data-workbench-theme='light']) .cs-decision p,
html:not([data-workbench-theme='light']) .cs-action-row {
  color: #f8fafc;
}
</style>
