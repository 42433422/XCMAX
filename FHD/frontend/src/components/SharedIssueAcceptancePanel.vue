<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { apiFetch } from '@/utils/apiBase'

interface Repair {
  id: number; ticket_no: string; summary: string; ready: boolean; state?: string; last_error?: string
  can_resolve?: boolean; can_reopen?: boolean; latest_result?: { team_ok?: boolean; progress?: string; source?: string; fault_remains?: boolean } | null
}
type Decision = 'resolved' | 'reopen'
interface RequestAttempt { id: number; url: string; payload: Record<string, unknown>; message?: string }
const STATE_TEXT: Record<string, string> = {
  received: '已收到，等待 AI 处理。', reopened: '已重新打开，AI 正在重新处理。',
  awaiting_customer: '处理结果已提交，等待您确认。确认前工单不会关闭。',
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

function humanResult(repair: Repair) {
  const latest = repair.latest_result
  if (!latest?.progress) return ''
  if (latest.source === 'human' || typeof latest.fault_remains === 'boolean') return latest.progress
  return ''
}

function stateText(repair: Repair) {
  if (repair.ready) return '修复已到达当前客户端，请按原来的操作验证是否恢复。'
  if (repair.state === 'resolved' || repair.state === 'closed') return '工单已关闭，如问题仍存在可以重新打开。'
  return STATE_TEXT[repair.state || ''] || '修复尚未到达当前客户端，工单将继续跟进交付。'
}

type Tone = 'info' | 'success' | 'warning' | 'danger' | 'neutral'

/** 工单状态徽标：用颜色区分「处理中 / 待确认 / 已关闭 / 失败」。 */
function stateBadge(repair: Repair): { label: string; tone: Tone } {
  if (repair.ready) return { label: '可验证', tone: 'success' }
  if (repair.state === 'resolved' || repair.state === 'closed') return { label: '已关闭', tone: 'neutral' }
  if (repair.state === 'awaiting_customer') return { label: '待您确认', tone: 'warning' }
  if (repair.state === 'awaiting_delivery') return { label: '待发布', tone: 'info' }
  if (repair.state === 'repair_failed' || repair.state === 'dispatch_failed') return { label: '需重试', tone: 'danger' }
  if (repair.state === 'reopened') return { label: '重新处理中', tone: 'info' }
  if (repair.state === 'received') return { label: '已收到', tone: 'info' }
  return { label: '处理中', tone: 'info' }
}

/** 工单号过长时中段省略，保留首尾便于人工核对，完整值放 title。 */
function ticketLabel(ticketNo: string): string {
  const value = String(ticketNo || '').trim()
  return value.length > 18 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value
}

/**
 * AI 进度串（如「排查中：修复中：验证中」）拆成阶段步骤。
 * 只有可被拆成多个短语时才展示步骤条，普通句子仍按原样显示。
 */
function progressSteps(repair: Repair): string[] {
  const raw = String(repair.latest_result?.progress || '').trim()
  if (!raw) return []
  const parts = raw.split(/[：:；;→>]+/).map((part) => part.trim()).filter(Boolean)
  if (parts.length < 2 || parts.some((part) => part.length > 10)) return []
  return parts
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
    if (response.status === 401) throw new Error('登录已失效，请重新登录后重试同步工单')
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
  <section class="repair-acceptance">
    <button ref="trigger" class="repair-trigger" type="button" :aria-expanded="opened" aria-haspopup="dialog" @click="openResults">问题工单处理结果（{{ repairs.length }}）<span v-if="error || failed" class="repair-trigger-error"> · 同步或保存失败</span></button>
    <Teleport to="body">
    <dialog v-if="opened" ref="dialog" aria-label="问题工单处理结果" class="repair-dialog" @cancel.prevent="closeResults" @click="($event.target === dialog) && closeResults()">
      <header class="repair-header">
        <div class="repair-heading">
          <span class="repair-heading-icon" aria-hidden="true">◎</span>
          <strong>问题工单处理结果</strong>
          <span class="repair-count">{{ repairs.length }}</span>
        </div>
        <div class="repair-header-actions">
          <button type="button" class="repair-ghost" :disabled="loading || busy !== null" @click="refresh">刷新</button>
          <button type="button" class="repair-ghost" autofocus @click="closeResults">关闭</button>
        </div>
      </header>
      <div class="repair-list">
        <div v-if="loading" class="repair-skeletons" role="status">
          <span>正在同步工单…</span>
          <div class="repair-skeleton" /><div class="repair-skeleton" />
        </div>
        <div v-else-if="!repairs.length && !error && !failed" class="repair-empty">
          <span class="repair-empty-icon" aria-hidden="true">✓</span>
          <p>当前没有待核对的工单</p>
          <small>修复交付后，这里会出现需要您验证的工单。</small>
        </div>
        <p v-if="error || failed" class="repair-alert" role="alert">
          {{ error || failed?.message }}
          <button type="button" class="repair-link" :disabled="busy !== null" @click="retry">重试</button>
        </p>
        <article v-for="repair in repairs" :key="repair.id" class="repair-card">
          <div class="repair-card-head">
            <code class="repair-ticket" :title="repair.ticket_no">{{ ticketLabel(repair.ticket_no) }}</code>
            <span class="repair-badge" :data-tone="stateBadge(repair).tone">{{ stateBadge(repair).label }}</span>
          </div>
          <details class="repair-description"><summary>{{ repair.summary.slice(0, 64) }}{{ repair.summary.length > 64 ? '…' : '' }}</summary><p>{{ repair.summary }}</p></details>
          <p class="repair-state">{{ stateText(repair) }}</p>
          <ol v-if="progressSteps(repair).length" class="repair-steps">
            <li v-for="(step, index) in progressSteps(repair)" :key="`${repair.id}-${index}`"
                :data-current="index === progressSteps(repair).length - 1">
              <span class="repair-step-dot" aria-hidden="true" />{{ step }}
            </li>
          </ol>
          <p v-if="humanResult(repair)" class="repair-result">处理结果：{{ humanResult(repair) }}</p>
          <p v-else-if="repair.latest_result?.progress && !progressSteps(repair).length" class="repair-result">AI 处理结果：{{ repair.latest_result.progress }}</p>
          <p v-if="repair.last_error" class="repair-alert repair-alert-inline">失败原因：{{ repair.last_error }}</p>
          <div v-if="repair.ready || repair.can_resolve || repair.can_reopen" class="repair-compose">
            <label :for="`repair-result-${repair.id}`">使用结果</label>
            <input :id="`repair-result-${repair.id}`" v-model="notes[repair.id]" maxlength="2000" placeholder="例如：现在可以正常保存订单了" />
            <div class="repair-buttons">
              <button v-if="repair.ready" type="button" class="repair-primary" :disabled="busy !== null || (notes[repair.id] || '').trim().length < 4" @click="submit(repair)">
                {{ busy === repair.id ? '正在保存…' : '确认原问题已解决' }}
              </button>
              <button v-else-if="repair.can_resolve" type="button" class="repair-primary" :disabled="busy !== null || (notes[repair.id] || '').trim().length < 4" @click="submit(repair, 'resolved')">
                {{ busy === repair.id ? '正在保存…' : '已解决' }}
              </button>
              <button v-if="repair.can_reopen" type="button" class="repair-secondary" :disabled="busy !== null || (notes[repair.id] || '').trim().length < 4" @click="submit(repair, 'reopen')">
                仍未解决，重新打开
              </button>
            </div>
          </div>
        </article>
      </div>
    </dialog>
    </Teleport>
  </section>
</template>

<style scoped>
.repair-acceptance { flex: none; min-width: 0; }
.repair-trigger { padding: 6px 12px; border: 1px solid var(--xc-color-border, #dbe3f0); border-radius: 999px; background: var(--xc-color-surface, #fff); color: var(--xc-color-text, #1f2329); font-size: 13px; line-height: 1.4; }
.repair-trigger:hover, .repair-trigger:focus-visible { border-color: var(--xc-color-primary, #2d7bd6); color: var(--xc-color-primary, #2d7bd6); }
.repair-trigger-error { color: var(--xc-color-danger, #b42318); }

.repair-dialog {
  box-sizing: border-box; display: flex; flex-direction: column;
  width: min(720px, calc(100vw - 32px)); max-height: 82dvh; padding: 0;
  border: 1px solid var(--xc-color-border, #e3e8f0); border-radius: 16px;
  color: var(--xc-color-text, #1f2329); background: var(--xc-color-surface, #fff);
  box-shadow: 0 24px 60px -12px #10182833, 0 8px 20px -8px #1018281f;
  overflow: hidden;
}
.repair-dialog::backdrop { background: #0b122054; backdrop-filter: blur(2px); }
.repair-dialog p { margin: 0; }
.repair-dialog button { font: inherit; cursor: pointer; border-radius: 8px; }
.repair-dialog button:disabled { cursor: default; opacity: .55; }
.repair-dialog input { box-sizing: border-box; font: inherit; border: 1px solid var(--xc-color-border, #dbe3f0); border-radius: 8px; background: var(--xc-color-surface, #fff); color: inherit; }

.repair-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 20px; border-bottom: 1px solid var(--xc-color-border, #eef1f6); background: var(--xc-color-surface, #fff); }
.repair-heading { display: flex; align-items: center; gap: 8px; font-size: 15px; }
.repair-heading-icon { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 8px; background: #e8f1fd; color: #2d7bd6; font-size: 15px; }
.repair-count { min-width: 22px; padding: 1px 7px; border-radius: 999px; background: #eef1f6; color: #5b6472; font-size: 12px; text-align: center; }
.repair-header-actions { display: flex; gap: 8px; }
.repair-ghost { padding: 6px 14px; border: 1px solid var(--xc-color-border, #dbe3f0); background: transparent; color: #475467; }
.repair-ghost:hover:not(:disabled), .repair-ghost:focus-visible { border-color: #2d7bd6; color: #2d7bd6; }

.repair-list { flex: 1 1 auto; display: flex; flex-direction: column; gap: 12px; padding: 16px 20px 20px; overflow: auto; overflow-wrap: anywhere; background: #f7f9fc; }
.repair-card { padding: 16px; border: 1px solid #e6ebf3; border-radius: 12px; background: var(--xc-color-surface, #fff); box-shadow: 0 1px 2px #1018280d; }
.repair-card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.repair-ticket { padding: 3px 8px; border-radius: 6px; background: #f2f4f7; color: #475467; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.repair-badge { padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.repair-badge[data-tone='info'] { background: #e8f1fd; color: #1a63bd; }
.repair-badge[data-tone='success'] { background: #e7f6ec; color: #157f3b; }
.repair-badge[data-tone='warning'] { background: #fdf3e2; color: #a15c07; }
.repair-badge[data-tone='danger'] { background: #fdeceb; color: #b42318; }
.repair-badge[data-tone='neutral'] { background: #eef1f6; color: #5b6472; }

.repair-description { margin-bottom: 8px; font-size: 14px; line-height: 1.55; }
.repair-description summary { cursor: pointer; color: #1f2329; }
.repair-description p { margin-top: 8px; padding: 10px 12px; border-radius: 8px; background: #f7f9fc; color: #475467; white-space: pre-wrap; }
.repair-state { margin-bottom: 10px !important; color: #475467; font-size: 13px; line-height: 1.5; }

.repair-steps { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; padding: 0; list-style: none; }
.repair-steps li { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; background: #f2f4f7; color: #667085; font-size: 12px; }
.repair-steps li[data-current='true'] { background: #e8f1fd; color: #1a63bd; font-weight: 600; }
.repair-step-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: .5; }
.repair-steps li[data-current='true'] .repair-step-dot { opacity: 1; }

.repair-result { margin-bottom: 10px !important; padding: 10px 12px; border-left: 3px solid #2d7bd6; border-radius: 0 8px 8px 0; background: #f4f8fe; color: #344054; font-size: 13px; line-height: 1.6; }

.repair-alert { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 10px !important; padding: 10px 12px; border-radius: 8px; background: #fdeceb; color: #b42318; font-size: 13px; }
.repair-alert-inline { border-left: 3px solid #e14b3f; border-radius: 0 8px 8px 0; }
.repair-link { padding: 0; border: none; background: none; color: #b42318; font-size: 13px; text-decoration: underline; }

.repair-compose { padding-top: 12px; border-top: 1px dashed #e6ebf3; }
.repair-compose label { display: block; margin-bottom: 6px; color: #475467; font-size: 12px; }
.repair-compose input { display: block; width: 100%; padding: 8px 10px; }
.repair-compose input:focus { outline: none; border-color: #2d7bd6; box-shadow: 0 0 0 3px #2d7bd61f; }
.repair-buttons { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.repair-primary { padding: 7px 16px; border: 1px solid #2d7bd6; background: #2d7bd6; color: #fff; }
.repair-primary:hover:not(:disabled) { background: #1a63bd; }
.repair-secondary { padding: 7px 16px; border: 1px solid var(--xc-color-border, #dbe3f0); background: var(--xc-color-surface, #fff); color: #475467; }
.repair-secondary:hover:not(:disabled) { border-color: #b42318; color: #b42318; }

.repair-empty { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 48px 16px; text-align: center; color: #667085; }
.repair-empty-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 50%; background: #e7f6ec; color: #157f3b; font-size: 20px; }
.repair-empty p { font-size: 14px; color: #344054; }
.repair-empty small { font-size: 12px; }
.repair-skeletons { display: flex; flex-direction: column; gap: 12px; color: #667085; font-size: 13px; }
.repair-skeleton { height: 92px; border-radius: 12px; background: linear-gradient(90deg, #eef1f6 25%, #f7f9fc 50%, #eef1f6 75%); background-size: 200% 100%; animation: repair-shimmer 1.2s ease-in-out infinite; }
@keyframes repair-shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }
</style>
