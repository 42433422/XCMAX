<template>
  <section class="cs-card">
    <div class="cs-card__head">
      <span class="cs-card__type">{{ title }}</span>
      <span v-if="status" :class="['cs-card__status', `cs-card__status--${status}`]">{{ statusLabel }}</span>
    </div>

    <div v-if="card.type === 'ticket'" class="cs-grid">
      <div><b>工单号</b><span>{{ card.ticket_no || '—' }}</span></div>
      <div><b>场景</b><span>{{ card.intent || 'general' }}</span></div>
      <div><b>对象</b><span>{{ card.subject_type || '—' }} {{ card.subject_id || '' }}</span></div>
      <div><b>状态</b><span>{{ card.status || '—' }}</span></div>
    </div>

    <div v-else-if="card.type === 'decision'" class="cs-decision">
      <p>{{ card.rationale || '已完成审核判断。' }}</p>
      <div class="cs-grid">
        <div><b>结论</b><span>{{ card.decision || '—' }}</span></div>
        <div><b>风险</b><span>{{ card.risk_level || 'low' }}</span></div>
        <div><b>置信度</b><span>{{ confidenceText }}</span></div>
      </div>
    </div>

    <div v-else-if="card.type === 'actions'" class="cs-actions">
      <div v-for="item in card.items || []" :key="item.id || item.action_type" class="cs-action-row">
        <span>{{ item.action_type }}</span>
        <span :class="['cs-card__status', `cs-card__status--${item.status}`]">{{ item.status }}</span>
      </div>
    </div>

    <pre v-else class="cs-json">{{ card }}</pre>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  card: Record<string, any>
}>()

const title = computed(() => {
  if (props.card.type === 'ticket') return '工单'
  if (props.card.type === 'decision') return '审核标准'
  if (props.card.type === 'actions') return '自动动作'
  return '客服卡片'
})

const status = computed(() => String(props.card.status || props.card.decision || '').trim())
const statusLabel = computed(() => status.value || 'pending')
const confidenceText = computed(() => {
  const n = Number(props.card.confidence || 0)
  return n > 0 ? `${Math.round(n * 100)}%` : '—'
})
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
