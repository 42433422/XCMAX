<template>
  <!-- 未知/内部卡片（如 intent）不对客户展示，避免露出调试 JSON -->
  <section v-if="isCustomerFacing" class="cs-card">
    <div class="cs-card__head">
      <span class="cs-card__type">{{ title }}</span>
      <span v-if="statusLabel" :class="['cs-card__status', `cs-card__status--${statusKey}`]">
        {{ statusLabel }}
      </span>
    </div>

    <div v-if="card.type === 'ticket'" class="cs-plain">
      <p>{{ ticketSummary }}</p>
      <p v-if="subjectHint" class="cs-plain__meta">{{ subjectHint }}</p>
    </div>

    <div v-else-if="card.type === 'decision'" class="cs-plain">
      <p>{{ humanRationale }}</p>
      <p class="cs-plain__meta">{{ decisionLabel }}</p>
    </div>

    <div v-else-if="card.type === 'actions'" class="cs-actions">
      <div v-for="item in visibleActions" :key="String(item.id || item.action_type || '')" class="cs-action-row">
        <span>{{ actionLabel(item.action_type) }}</span>
        <span :class="['cs-card__status', `cs-card__status--${displayActionStatus(item)}`]">
          {{ actionStatusText(displayActionStatus(item)) }}
        </span>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ticketIntentLabel, ticketLifecycleLabel } from '../../utils/csTicketLifecycle'

interface CustomerServiceAction {
  id?: unknown
  action_type?: unknown
  status?: unknown
  [key: string]: unknown
}

interface CustomerServiceCard {
  type?: unknown
  intent?: unknown
  subject_type?: unknown
  subject_id?: unknown
  decision?: unknown
  rationale?: unknown
  status?: unknown
  decision_status?: unknown
  lifecycle_stage?: unknown
  lifecycle_label?: unknown
  items?: unknown[]
  [key: string]: unknown
}

const props = defineProps<{
  card: CustomerServiceCard
}>()

const CUSTOMER_FACING = new Set(['ticket', 'decision', 'actions'])

const isCustomerFacing = computed(() => CUSTOMER_FACING.has(String(props.card?.type || '')))

const title = computed(() => {
  if (props.card.type === 'ticket') return '进度'
  if (props.card.type === 'decision') return '下一步'
  if (props.card.type === 'actions') return '已办理'
  return ''
})

const intentLabel = computed(() => ticketIntentLabel(props.card.intent))

const subjectHint = computed(() => {
  const typeMap: Record<string, string> = {
    order: '相关订单',
    catalog_item: '相关商品',
    account: '相关账号',
    llm_model: '相关模型',
  }
  const t = String(props.card.subject_type || '')
  const id = String(props.card.subject_id || '').trim()
  const label = typeMap[t] || ''
  if (!label) return ''
  return id ? `${label}：${id}` : label
})

const ticketSummary = computed(() => {
  const kind = intentLabel.value
  const stage = ticketLifecycleLabel(props.card)
  if (stage === '待补充') return `你的${kind}还缺一些信息，请在对话里直接补充。`
  if (stage === '处理中' || stage === '已收到') return `你的${kind}已收到，正在处理。`
  if (stage === '有结果') return `你的${kind}已有处理结果。`
  if (stage === '已完成') return `你的${kind}已处理完成。`
  return `你的${kind}进度：${stage}`
})

const decisionLabel = computed(() => {
  const map: Record<string, string> = {
    approved: '已开始处理',
    rejected: '未能通过',
    needs_more_info: '请先补充信息',
  }
  return map[String(props.card.decision || '')] || ''
})

const humanRationale = computed(() => humanizeUserText(String(props.card.rationale || '')))

const statusKey = computed(() => {
  const raw = String(props.card.status || props.card.decision || '').toLowerCase().replace(/\s+/g, '_')
  return raw || 'pending'
})

const statusLabel = computed(() => {
  if (props.card.type === 'actions') return ''
  return ticketLifecycleLabel(props.card)
})

function humanizeUserText(text: string) {
  let s = text || ''
  const map: Record<string, string> = {
    order_no: '订单号',
    catalog_id: '商品编号',
    complaint_type: '问题类型',
    reason: '原因说明',
    provider: '模型厂商',
    model: '模型名称',
    needs_more_info: '需补充材料',
    approved: '已受理',
    rejected: '未通过',
  }
  for (const [k, v] of Object.entries(map)) {
    s = s.split(k).join(v)
  }
  // 去掉重复「还需要补充：还需要补充」
  s = s.replace(/还需要补充：还需要补充/g, '还需要补充')
  return s.trim() || '已根据你的说明给出处理结论。'
}

/** 员工跟进进度写回勿对用户显示「转交失败」红字 */
const visibleActions = computed(() => {
  const items = Array.isArray(props.card.items) ? props.card.items : []
  // 同类型只保留最近一条，避免三次回写叠三条失败行
  const seen = new Set<string>()
  const out: CustomerServiceAction[] = []
  for (const item of [...items].reverse()) {
    if (typeof item !== 'object' || item === null || Array.isArray(item)) continue
    const action = item as CustomerServiceAction
    const key = String(action.action_type || action.id || '')
    if (!key || seen.has(key)) continue
    seen.add(key)
    out.push(action)
  }
  return out.reverse()
})

function displayActionStatus(item: CustomerServiceAction) {
  const type = String(item?.action_type || '')
  const status = String(item?.status || '').toLowerCase()
  if (type === 'employee.dispatch' && status === 'failed') return 'running'
  return status
}

function actionStatusText(raw: unknown) {
  const s = String(raw || '').toLowerCase()
  const map: Record<string, string> = {
    completed: '已完成',
    running: '进行中',
    failed: '失败',
    skipped: '已跳过',
    pending: '待处理',
  }
  return map[s] || (raw ? String(raw) : '')
}

function actionLabel(raw: unknown) {
  const s = String(raw || '')
  const map: Record<string, string> = {
    'refund.apply': '退款申请',
    'catalog.complaint.create': '投诉登记',
    'catalog.compliance.review': '合规审核',
    'llm.model_capability.propose': '模型扩展申请',
    'employee.dispatch': '员工跟进',
  }
  return map[s] || '处理动作'
}
</script>

<style scoped>
.cs-card {
  margin-top: 8px;
  border: 1px solid color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 10%, transparent);
  border-radius: 12px;
  padding: 10px 12px;
  background: color-mix(in srgb, var(--wb-text-primary, #1d1d1f) 3%, transparent);
}

.cs-card__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.cs-card__type {
  font-size: 0.78rem;
  font-weight: 750;
  color: var(--wb-text-secondary, #6e6e73);
}

.cs-card__status {
  display: inline-flex;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 700;
  background: color-mix(in srgb, var(--wb-accent-primary, #0071e3) 12%, transparent);
  color: var(--wb-accent-primary, #0071e3);
}

.cs-card__status--failed,
.cs-card__status--rejected {
  background: color-mix(in srgb, #c9342d 14%, transparent);
  color: #c9342d;
}

.cs-card__status--needs_more_info,
.cs-card__status--waiting_user {
  background: color-mix(in srgb, #b36b00 14%, transparent);
  color: #b36b00;
}

.cs-card__status--resolved,
.cs-card__status--done,
.cs-card__status--closed,
.cs-card__status--completed,
.cs-card__status--approved {
  background: color-mix(in srgb, #248a3d 14%, transparent);
  color: #248a3d;
}

.cs-plain p {
  margin: 0;
  font-size: 0.86rem;
  line-height: 1.45;
}

.cs-plain__meta {
  margin-top: 4px !important;
  font-size: 0.76rem !important;
  color: var(--wb-text-secondary, #6e6e73);
}

.cs-actions {
  display: grid;
  gap: 6px;
}

.cs-action-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 0.82rem;
}

html:not([data-workbench-theme='light']) .cs-card {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.12);
}

html:not([data-workbench-theme='light']) .cs-card__type,
html:not([data-workbench-theme='light']) .cs-plain__meta {
  color: rgba(255, 255, 255, 0.62);
}
</style>
