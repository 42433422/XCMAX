<template>
  <!-- 未知/内部卡片（如 intent）不对客户展示，避免露出调试 JSON -->
  <section v-if="isCustomerFacing" class="cs-card">
    <div class="cs-card__head">
      <span class="cs-card__type">{{ title }}</span>
      <span v-if="status" :class="['cs-card__status', `cs-card__status--${status}`]">{{ statusLabel }}</span>
    </div>

    <div v-if="card.type === 'ticket'" class="cs-grid">
      <div><b>工单号</b><span>{{ card.ticket_no || '—' }}</span></div>
      <div><b>场景</b><span>{{ intentLabel }}</span></div>
      <div><b>对象</b><span>{{ card.subject_type || '—' }} {{ card.subject_id || '' }}</span></div>
      <div><b>状态</b><span>{{ card.status || '—' }}</span></div>
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
        <span :class="['cs-card__status', `cs-card__status--${item.status}`]">{{ statusText(item.status) }}</span>
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
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.06);
  border-radius: 18px;
  padding: 14px;
  margin-top: 10px;
}

.cs-card__head,
.cs-action-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.cs-card__type {
  color: #f7e9bf;
  font-weight: 800;
}

.cs-card__status {
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 999px;
  padding: 4px 9px;
  color: #d7fbe8;
  background: rgba(35, 195, 126, 0.12);
  font-size: 12px;
}

.cs-card__status--failed,
.cs-card__status--rejected {
  color: #ffd3d3;
  background: rgba(255, 72, 72, 0.14);
}

.cs-card__status--needs_more_info,
.cs-card__status--waiting_user {
  color: #ffe4a3;
  background: rgba(255, 180, 51, 0.14);
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
  color: rgba(255, 255, 255, 0.56);
  font-size: 12px;
}

.cs-grid span,
.cs-decision p,
.cs-action-row {
  color: rgba(255, 255, 255, 0.9);
}

.cs-actions {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.cs-json {
  margin-top: 10px;
  white-space: pre-wrap;
  color: rgba(255, 255, 255, 0.75);
}
</style>
