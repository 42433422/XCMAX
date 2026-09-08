<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import agentRunsApi, { type AgentSchedule } from '@/api/agentRuns'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

const schedules = ref<AgentSchedule[]>([])
const error = ref('')
const busy = ref(false)
let generation = 0

async function refresh() {
  const current = ++generation
  busy.value = true
  error.value = ''
  try {
    const response = await agentRunsApi.listSchedules()
    if (current !== generation) return
    if (!response.success) throw new Error('load failed')
    schedules.value = response.data || []
  } catch {
    if (current === generation) error.value = '周期计划读取失败，请刷新重试。'
  } finally {
    if (current === generation) busy.value = false
  }
}

async function control(id: string, action: 'pause' | 'resume' | 'cancel') {
  if (busy.value) return
  const current = generation
  busy.value = true
  error.value = ''
  try {
    const response = await agentRunsApi.controlSchedule(id, action)
    if (current !== generation) return
    if (!response.success) throw new Error('control failed')
    await refresh()
  } catch {
    if (current === generation) error.value = '周期计划操作失败，请刷新确认实际状态。'
  } finally {
    if (current === generation) busy.value = false
  }
}

function ruleText(row: AgentSchedule) {
  const rule = row.payload.recurrence
  if (rule.kind === 'interval') return `每 ${rule.seconds} 秒`
  return `每天 ${String(rule.hour).padStart(2, '0')}:${String(rule.minute || 0).padStart(2, '0')}（${rule.timezone}）`
}

watch(productReadAccountEpoch, () => {
  ++generation
  schedules.value = []
  void refresh()
}, { flush: 'sync' })
onMounted(refresh)
onBeforeUnmount(() => { ++generation })
</script>

<template>
  <details class="recurring-plans">
    <summary>周期计划（{{ schedules.length }}）</summary>
    <p>可在对话中创建周期计划。每次任务仍须审批；暂停或取消计划只影响后续触发。</p>
    <button type="button" :disabled="busy" @click="refresh">刷新计划</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!busy && !schedules.length">当前账号没有周期计划。</p>
    <article v-for="row in schedules" :key="row.schedule_id">
      <strong>{{ row.payload.title }}</strong>
      <span>{{ { active: '已启用', paused: '已暂停', cancelled: '已取消' }[row.state] }} · {{ ruleText(row) }}</span>
      <span v-if="row.state !== 'cancelled'">下次触发：{{ new Date(row.next_run_at).toLocaleString() }}</span>
      <span v-if="row.last_error" role="alert">上次触发失败，请检查最近任务和计划状态。</span>
      <div>
        <button v-if="row.state === 'active'" type="button" :disabled="busy" @click="control(row.schedule_id, 'pause')">暂停</button>
        <button v-if="row.state === 'paused'" type="button" :disabled="busy" @click="control(row.schedule_id, 'resume')">恢复</button>
        <button v-if="row.state !== 'cancelled'" type="button" :disabled="busy" @click="control(row.schedule_id, 'cancel')">取消计划</button>
      </div>
    </article>
  </details>
</template>

<style scoped>
.recurring-plans { padding: 12px 18px; border-bottom: 1px solid var(--border-color, #ddd); }
summary { cursor: pointer; font-weight: 600; }
p, span { font-size: 12px; line-height: 1.6; }
article { display: grid; gap: 4px; margin-top: 12px; }
button { margin-right: 8px; padding: 4px 10px; }
[role='alert'] { color: #a83a2e; }
</style>
