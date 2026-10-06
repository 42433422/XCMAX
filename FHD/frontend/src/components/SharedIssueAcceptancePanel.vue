<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { apiFetch } from '@/utils/apiBase'

interface Repair {
  id: number; ticket_no: string; summary: string; ready: boolean; state?: string; last_error?: string
  can_resolve?: boolean; can_reopen?: boolean; latest_result?: { team_ok?: boolean; progress?: string } | null
}
type Decision = 'resolved' | 'reopen'
const STATE_TEXT: Record<string, string> = {
  received: '已收到，等待 AI 处理。', reopened: '已重新打开，AI 正在重新处理。',
  dispatch_failed: '派发处理失败，系统会自动重试。', awaiting_delivery: 'AI 已提交处理结果，等待正式发布。',
  repair_failed: 'AI 未能完成修复，可以说明情况后重新打开。', awaiting_customer_verification: '修复已发布，等待您验证。',
}
const account = useAccountProfileStore()
const repairs = ref<Repair[]>([])
const notes = ref<Record<number, string>>({})
const error = ref('')
const busy = ref<number | null>(null)
let attempts: Record<number, { decision: Decision; note: string; key: string }> = {}
let generation = 0
let pending: AbortController | undefined

function decisionKey(id: number, decision: Decision) {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`
  return `${id}-${decision}-${random}`
}

function stateText(repair: Repair) {
  if (repair.ready) return '修复已到达当前客户端，请按原来的操作验证是否恢复。'
  if (repair.can_resolve === false) return '工单已关闭，如问题仍存在可以重新打开。'
  return STATE_TEXT[repair.state || ''] || '修复尚未到达当前客户端，工单将继续跟进交付。'
}

async function refresh() {
  const current = ++generation
  pending?.abort()
  const controller = new AbortController()
  pending = controller
  repairs.value = []
  notes.value = {}
  attempts = {}
  busy.value = null
  error.value = ''
  if (account.marketUserId === null) return
  try {
    const response = await apiFetch('/api/mod-store/issue-runtime', { signal: controller.signal })
    if (response.status === 401) return
    const body = await response.json()
    if (!response.ok || body.success !== true) throw new Error('工单处理结果暂时无法同步，请重试')
    if (current === generation) repairs.value = Array.isArray(body.data?.items) ? body.data.items : []
  } catch (cause) {
    if (current === generation && !controller.signal.aborted) error.value = cause instanceof Error ? cause.message : '工单处理结果暂时无法同步'
  }
}

async function submit(repair: Repair, decision?: Decision) {
  const note = (notes.value[repair.id] || '').trim()
  if (note.length < 4 || busy.value !== null) return
  const current = generation
  let url = `/api/mod-store/issue-runtime/${repair.id}`
  let payload: Record<string, unknown> = { confirmed: true, note }
  if (decision) {
    const prior = attempts[repair.id]
    const key = prior?.decision === decision && prior.note === note ? prior.key : decisionKey(repair.id, decision)
    attempts[repair.id] = { decision, note, key }
    url += '/decision'
    payload = { decision, note, idempotency_key: key }
  }
  busy.value = repair.id
  error.value = ''
  try {
    const response = await apiFetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: pending?.signal,
    })
    const body = await response.json()
    if (!response.ok || body.success !== true) throw new Error(typeof body.detail === 'string' ? body.detail : '操作未成功保存，请重试')
    if (current === generation) await refresh()
  } catch (cause) {
    if (current === generation && !pending?.signal.aborted) error.value = cause instanceof Error ? cause.message : '操作未成功保存'
  } finally {
    if (current === generation) busy.value = null
  }
}

watch(() => [account.tenantId, account.marketUserId, account.localUserId, account.impersonatingMarketUserId], refresh, { immediate: true })
onBeforeUnmount(() => { generation++; pending?.abort() })
</script>

<template>
  <section v-if="repairs.length || error" class="repair-acceptance" aria-label="问题工单处理结果">
    <p v-if="error" role="alert">{{ error }} <button type="button" @click="refresh">重试</button></p>
    <article v-for="repair in repairs" :key="repair.id">
      <strong>{{ repair.ticket_no }} · {{ repair.summary }}</strong>
      <p>{{ stateText(repair) }}</p>
      <p v-if="repair.latest_result?.progress">AI 处理结果：{{ repair.latest_result.progress }}</p>
      <p v-if="repair.last_error">失败原因：{{ repair.last_error }}</p>
      <template v-if="repair.ready || repair.can_resolve || repair.can_reopen">
        <label :for="`repair-result-${repair.id}`">使用结果</label>
        <input :id="`repair-result-${repair.id}`" v-model="notes[repair.id]" maxlength="2000" placeholder="例如：现在可以正常保存订单了" />
        <button v-if="repair.ready" type="button" :disabled="busy !== null || (notes[repair.id] || '').trim().length < 4" @click="submit(repair)">
          {{ busy === repair.id ? '正在保存…' : '确认原问题已解决' }}
        </button>
        <button v-else-if="repair.can_resolve" type="button" :disabled="busy !== null || (notes[repair.id] || '').trim().length < 4" @click="submit(repair, 'resolved')">
          {{ busy === repair.id ? '正在保存…' : '已解决' }}
        </button>
        <button v-if="repair.can_reopen" type="button" :disabled="busy !== null || (notes[repair.id] || '').trim().length < 4" @click="submit(repair, 'reopen')">
          仍未解决，重新打开
        </button>
      </template>
    </article>
  </section>
</template>

<style scoped>
.repair-acceptance { padding: 16px 24px; border-bottom: 1px solid var(--border-color, #ddd); max-height: 40vh; overflow: auto; }
article + article { margin-top: 16px; }
p { margin: 8px 0; }
input { margin: 0 12px; padding: 8px; min-width: 240px; max-width: 100%; }
button { padding: 8px 12px; cursor: pointer; }
button + button { margin-left: 8px; }
button:disabled { cursor: default; opacity: .6; }
</style>
