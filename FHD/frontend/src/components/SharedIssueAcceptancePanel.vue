<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { apiFetch } from '@/utils/apiBase'

interface Repair {
  id: number; ticket_no: string; summary: string; ready: boolean; state?: string; last_error?: string
  can_resolve?: boolean; can_reopen?: boolean; latest_result?: { team_ok?: boolean; progress?: string } | null
}
type Decision = 'resolved' | 'reopen'
interface RequestAttempt { id: number; url: string; payload: Record<string, unknown>; message?: string }
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
const failed = ref<RequestAttempt | null>(null)
const dialog = ref<HTMLDialogElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const opened = ref(false)
const loading = ref(false)
let attempts: Record<number, { decision: Decision; note: string; key: string }> = {}
let generation = 0
let pending: AbortController | undefined

function decisionKey(id: number, decision: Decision) {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`
  return `${id}-${decision}-${random}`
}

function stateText(repair: Repair) {
  if (repair.ready) return '修复已到达当前客户端，请按原来的操作验证是否恢复。'
  if (repair.state === 'resolved' || repair.state === 'closed') return '工单已关闭，如问题仍存在可以重新打开。'
  return STATE_TEXT[repair.state || ''] || '修复尚未到达当前客户端，工单将继续跟进交付。'
}

async function refresh() {
  const current = ++generation
  pending?.abort()
  const controller = new AbortController()
  pending = controller
  repairs.value = []
  busy.value = null
  if (!failed.value) error.value = ''
  loading.value = account.marketUserId !== null
  if (account.marketUserId === null) return
  try {
    const response = await apiFetch('/api/mod-store/issue-runtime', { signal: controller.signal })
    if (response.status === 401) return
    const body = await response.json()
    if (!response.ok || body.success !== true) throw new Error('工单处理结果暂时无法同步，请重试')
    if (current === generation) repairs.value = Array.isArray(body.data?.items) ? body.data.items : []
  } catch (cause) {
    if (current === generation && !controller.signal.aborted) error.value = cause instanceof Error ? cause.message : '工单处理结果暂时无法同步'
  } finally {
    if (current === generation) loading.value = false
  }
}

async function submit(repair: Repair, decision?: Decision) {
  const note = (notes.value[repair.id] || '').trim()
  if (note.length < 4 || busy.value !== null) return
  let url = `/api/mod-store/issue-runtime/${repair.id}`
  let payload: Record<string, unknown> = { confirmed: true, note }
  if (decision) {
    const prior = attempts[repair.id]
    const key = prior?.decision === decision && prior.note === note ? prior.key : decisionKey(repair.id, decision)
    attempts[repair.id] = { decision, note, key }
    url += '/decision'
    payload = { decision, note, idempotency_key: key }
  }
  await send({ id: repair.id, url, payload })
}

async function send(request: RequestAttempt) {
  if (busy.value !== null) return
  const current = generation
  busy.value = request.id
  error.value = ''
  try {
    const response = await apiFetch(request.url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request.payload), signal: pending?.signal,
    })
    const body = await response.json()
    if (!response.ok || body.success !== true) throw new Error(typeof body.detail === 'string' ? body.detail : '操作未成功保存，请重试')
    if (current === generation) {
      if (failed.value?.id === request.id) failed.value = null
      delete attempts[request.id]
      delete notes.value[request.id]
      await refresh()
    }
  } catch (cause) {
    if (current === generation && !pending?.signal.aborted) {
      error.value = cause instanceof Error ? cause.message : '操作未成功保存'
      failed.value = { ...request, message: error.value }
    }
  } finally {
    if (current === generation) busy.value = null
  }
}

function retry() { return failed.value ? send(failed.value) : refresh() }
async function openResults() {
  opened.value = true
  await nextTick()
  dialog.value?.showModal()
}
function closeResults() {
  dialog.value?.close()
  opened.value = false
  trigger.value?.focus()
}
watch(() => [account.tenantId, account.marketUserId, account.localUserId, account.impersonatingMarketUserId], () => {
  closeResults(); failed.value = null; attempts = {}; notes.value = {}; return refresh()
}, { immediate: true })
onBeforeUnmount(() => { generation++; pending?.abort() })
</script>

<template>
  <section v-if="repairs.length || error || failed || opened" class="repair-acceptance">
    <button ref="trigger" type="button" :aria-expanded="opened" aria-haspopup="dialog" @click="openResults">问题工单处理结果（{{ repairs.length }}）<span v-if="error || failed"> · 同步或保存失败</span></button>
    <Teleport to="body">
    <dialog v-if="opened" ref="dialog" aria-label="问题工单处理结果" class="repair-dialog" @cancel.prevent="closeResults" @click="($event.target === dialog) && closeResults()">
    <header><strong>问题工单处理结果（{{ repairs.length }}）</strong><button type="button" :disabled="loading || busy !== null" @click="refresh">刷新</button><button type="button" autofocus @click="closeResults">关闭</button></header>
    <div class="repair-list">
    <p v-if="loading" role="status">正在同步工单…</p>
    <p v-else-if="!repairs.length && !error && !failed">当前没有待核对的工单。</p>
    <p v-if="error || failed" role="alert">{{ error || failed?.message }} <button type="button" :disabled="busy !== null" @click="retry">重试</button></p>
    <article v-for="repair in repairs" :key="repair.id">
      <strong>{{ repair.ticket_no }}</strong>
      <details class="repair-description"><summary>{{ repair.summary.slice(0, 64) }}{{ repair.summary.length > 64 ? '…' : '' }}</summary><p>{{ repair.summary }}</p></details>
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
    </div>
    </dialog>
    </Teleport>
  </section>
</template>

<style scoped>
.repair-acceptance { flex: none; min-width: 0; }
.repair-dialog { box-sizing: border-box; width: min(720px, calc(100vw - 32px)); max-height: 80dvh; padding: 0; border: 1px solid var(--xc-color-border, #ddd); border-radius: 12px; color: var(--xc-color-text, #1f2329); background: var(--xc-color-surface, #fff); }
.repair-dialog::backdrop { background: #0006; }
.repair-dialog header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 16px; }
.repair-list { max-height: 65dvh; overflow: auto; padding: 0 16px 16px; overflow-wrap: anywhere; }
.repair-description summary { font-weight: normal; line-height: 1.5; }
article { padding: 8px 0; border-top: 1px solid var(--border-color, #ddd); }
summary { cursor: pointer; }
.repair-acceptance span { color: var(--xc-color-danger, #b42318); }
article + article { margin-top: 16px; }
p { margin: 8px 0; }
input { box-sizing: border-box; display: block; margin: 8px 0; padding: 8px; width: min(360px, 100%); max-width: 100%; }
button { padding: 8px 12px; cursor: pointer; }
button + button { margin-left: 8px; }
button:disabled { cursor: default; opacity: .6; }
</style>
