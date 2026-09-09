<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import agentRunsApi, { type ScheduleConsent } from '@/api/agentRuns'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

const props = defineProps<{ scheduleId: string }>()
const emit = defineEmits<{ changed: [] }>()
const consent = ref<ScheduleConsent | null>(null)
const busy = ref(false)
const error = ref('')
const expiry = ref('')
const maxRuns = ref(10)
const confirmed = ref(false)
let generation = 0

async function inspect() {
  const current = ++generation
  busy.value = true
  error.value = ''
  confirmed.value = false
  try {
    const response = await agentRunsApi.inspectScheduleConsent(props.scheduleId)
    if (current !== generation) return
    if (!response.success || !response.data) throw new Error('unavailable')
    consent.value = response.data
  } catch {
    if (current === generation) error.value = '无法读取当前授权范围，请重试。'
  } finally {
    if (current === generation) busy.value = false
  }
}

async function change(revoke: boolean) {
  if (busy.value || !consent.value) return
  const current = generation
  if (!revoke && (!confirmed.value || !expiry.value || !Number.isInteger(maxRuns.value) || maxRuns.value < 1)) return
  busy.value = true
  error.value = ''
  try {
    const response = revoke
      ? await agentRunsApi.revokeScheduleConsent(props.scheduleId)
      : await agentRunsApi.authorizeSchedule(props.scheduleId, {
        scope_hash: consent.value.scope_hash,
        expires_at: new Date(expiry.value).toISOString(),
        max_runs: maxRuns.value,
      })
    if (current !== generation) return
    if (!response.success) throw new Error('rejected')
    await inspect()
    emit('changed')
  } catch {
    if (current === generation) error.value = '授权操作失败，请重新查看范围与实际状态。'
  } finally {
    if (current === generation) busy.value = false
  }
}

watch([productReadAccountEpoch, () => props.scheduleId], () => {
  ++generation
  consent.value = null
  busy.value = false
  confirmed.value = false
  error.value = ''
}, { flush: 'sync' })
onBeforeUnmount(() => { ++generation })
</script>

<template>
  <div class="schedule-consent">
    <button type="button" :disabled="busy" @click="inspect">查看自动执行授权</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <section v-if="consent" aria-label="周期自动执行授权">
      <strong>{{ consent.operation.tool_id }} · {{ consent.operation.action }}</strong>
      <pre>{{ JSON.stringify(consent.operation.params, null, 2) }}</pre>
      <p v-if="consent.authorization">
        授权截止 {{ new Date(consent.authorization.expires_at).toLocaleString() }}；
        已批准 {{ consent.authorization.reserved_runs }} / {{ consent.authorization.max_runs }} 次任务。
        <button type="button" :disabled="busy" @click="change(true)">撤销自动执行</button>
      </p>
      <p v-else>当前无自动执行授权，任务逐次审批。</p>
      <label>到期时间（本机时区）<input v-model="expiry" type="datetime-local" :disabled="busy"></label>
      <label>最多批准任务数<input v-model.number="maxRuns" type="number" min="1" max="1000000" :disabled="busy"></label>
      <label><input v-model="confirmed" type="checkbox" :disabled="busy">按当前动作、参数和周期规则，在以上期限及次数内自动执行。</label>
      <p>撤销会阻止尚未开始的自动任务；已开始的操作请在任务工作区查看和控制。</p>
      <button type="button" :disabled="busy || !confirmed || !expiry" @click="change(false)">确认授权自动执行</button>
    </section>
  </div>
</template>

<style scoped>
.schedule-consent { margin-top: 8px; }
section { display: grid; gap: 8px; margin-top: 8px; }
label { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 140px; overflow: auto; font-size: 12px; }
p { font-size: 12px; }
</style>
