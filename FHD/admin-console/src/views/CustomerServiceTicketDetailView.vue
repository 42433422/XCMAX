<template>
  <main class="cs-view" id="view-customer-service-ticket-detail">
    <nav class="cs-back"><button type="button" class="cs-btn" @click="backToList">← 返回工单列表</button></nav>
    <p v-if="!validId" role="alert" class="cs-banner-error">工单 ID 无效：{{ route.params.ticketId }}。请从工单列表打开。</p>
    <p v-else-if="loading" role="status" class="cs-card cs-state">正在读取原单证据…</p>
    <p v-else-if="error" role="alert" class="cs-banner-error">
      {{ error }} <button type="button" class="cs-btn" @click="load">重试详情</button>
    </p>
    <div v-else-if="detail" class="cs-detail" aria-label="客服原单详情">
      <section class="cs-card cs-hero">
        <div class="cs-hero-top">
          <div class="cs-hero-title">
            <span class="cs-kicker">客服原单 · 内部 ID {{ ticketId }}</span>
            <h2>{{ ticket.title || '（无标题）' }}</h2>
            <button type="button" class="cs-btn" :disabled="saving || savingEta" @click="correctTitle()">更正标题</button>
            <button v-if="canCorrectClassification" type="button" class="cs-btn" :disabled="saving || savingEta" @click="correctTitle(true)">纠正为平台功能问题</button>
            <code class="cs-ticket-no">{{ ticket.ticket_no }}</code>
          </div>
          <div class="cs-badges">
            <span class="cs-badge cs-badge-lg" :class="`is-${status.tone}`" :title="status.raw">{{ status.label }}</span>
            <span class="cs-tag">{{ submitterTypeLabel(ticket.submitter_type) }}</span>
            <span v-if="ticket.issue_domain_label" class="cs-tag">{{ ticket.issue_domain_label }}</span>
            <span class="cs-tag">{{ intentLabel(ticket.intent) }}</span>
            <span v-if="ticket.priority" class="cs-tag">优先级 {{ priorityLabel(ticket.priority) }}</span>
          </div>
        </div>
        <ol v-if="steps.length" class="cs-steps" aria-label="处理阶段">
          <li v-for="step in steps" :key="String(step.stage)" :class="`is-${step.state}`">{{ step.label }}</li>
        </ol>
        <dl class="cs-facts">
          <div><dt>客户</dt><dd>市场用户 ID {{ ticket.user_id ?? '—' }}<template v-if="ticket.session_id"> · 会话 {{ ticket.session_id }}</template></dd></div>
          <div><dt>提交人身份</dt><dd>{{ submitterTypeLabel(ticket.submitter_type) }}</dd></div>
          <div><dt>指派管理员</dt><dd>{{ ticket.assigned_admin_id || '暂无管理员指派记录' }}</dd></div>
          <div><dt>创建时间</dt><dd>{{ formatBeijingTime(ticket.created_at) }}</dd></div>
          <div><dt>最近更新</dt><dd>{{ formatBeijingTime(ticket.updated_at) }}</dd></div>
          <div><dt>关闭时间</dt><dd>{{ formatBeijingTime(ticket.closed_at, '未关闭') }}</dd></div>
          <div><dt>预期完成时间（客户可见）</dt><dd>{{ formatBeijingTime(ticket.expected_completion_at, '暂未安排') }}</dd></div>
        </dl>
        <form class="cs-eta-editor" @submit.prevent="saveExpectedCompletion">
          <label for="customer-ticket-eta">设置客户可见的预期完成时间（北京时间）</label><input id="customer-ticket-eta" v-model="expectedCompletionInput" type="datetime-local" />
          <button type="submit" class="cs-btn cs-btn-primary" :disabled="saving || savingEta">{{ savingEta ? '保存中…' : '保存时间' }}</button>
          <button v-if="ticket.expected_completion_at" type="button" class="cs-btn" :disabled="saving || savingEta" @click="clearExpectedCompletion">清除</button>
          <span v-if="etaMessage" role="status">{{ etaMessage }}</span>
          <span v-if="etaError" role="alert" class="cs-error-text">{{ etaError }}</span>
        </form>
        <p class="cs-hint">时间为北京时间（UTC+8）。处理状态本身不代表员工已领取或执行；以以下真实进度和审计记录为准。</p>
      </section>

      <section class="cs-card">
        <h3 class="cs-card-title">客户问题原文</h3>
        <p class="cs-quote">{{ ticket.summary || '原单未记录正文' }}</p>
      </section>

      <section class="cs-card" aria-label="执行总览">
        <h3 class="cs-card-title">执行总览</h3>
        <p v-if="!overview" class="cs-state">暂无执行总览证据，请查看原单进度记录。</p>
        <template v-else>
          <dl class="cs-facts">
            <div><dt>当前卡点</dt><dd>{{ overview.blocker }}</dd></div>
            <div><dt>当前责任方</dt><dd>{{ overview.responsible }}</dd></div>
            <div><dt>产品工作单</dt><dd>{{ overview.workOrder }}</dd></div>
            <div><dt>最近进展</dt><dd>{{ overview.progress }} · {{ overview.progressAt }}</dd></div>
            <div><dt>下一步</dt><dd>{{ overview.next }}</dd></div>
            <div><dt>修复核验来源</dt><dd>{{ overview.verificationSource }}</dd></div>
            <div><dt>正式版本与客户确认</dt><dd>{{ overview.release }} · {{ overview.customer }}</dd></div>
          </dl>
          <p v-if="!overview.receipts.length" class="cs-hint">当前事件尚无可核验的任务接单回执。</p>
          <ul v-else class="cs-chips" aria-label="实际接单凭证">
            <li v-for="receipt in overview.receipts" :key="receipt.key">
              {{ receipt.kind }} · {{ receipt.role }} · <code>{{ receipt.taskId }}</code>
              <span class="cs-badge" :class="`is-${receipt.badge.tone}`">{{ receipt.badge.label }}</span>
            </li>
          </ul>
        </template>
      </section>

      <CustomerServiceSharedRepair v-if="ticket.status === 'processing' && ticket.intent === 'product_issue' && !customDelivery"
        :key="ticketId" :ticket-id="ticketId" @linked="load" />

      <section class="cs-card">
        <h3 class="cs-card-title">处理结论</h3>
        <p v-if="!resolution" class="cs-state">暂无处理结论记录</p>
        <template v-else>
          <div class="cs-badges">
            <span class="cs-badge" :class="`is-${resolutionState.tone}`" :title="resolutionState.raw">{{ resolutionState.label }}</span>
            <span class="cs-badge" :class="`is-${repairVerified.tone}`">{{ repairVerified.label }}</span>
            <span v-if="resolution.route" class="cs-tag">{{ routeLabel(resolution.route) }}</span>
            <span v-if="resolution.incident_event_id" class="cs-tag">事件 #{{ resolution.incident_event_id }}</span>
          </div>
          <table v-if="team.length" class="cs-table cs-table-compact">
            <thead><tr><th>环节</th><th>处理员工</th><th>状态</th><th>结果</th></tr></thead>
            <tbody>
              <tr v-for="(m, i) in team" :key="i">
                <td>{{ m.role }}</td><td><code>{{ m.employee }}</code></td>
                <td><span class="cs-badge" :class="`is-${m.status.tone}`" :title="m.status.raw">{{ m.status.label }}</span></td>
                <td><span class="cs-badge" :class="`is-${m.ok.tone}`">{{ m.ok.label }}</span></td>
              </tr>
            </tbody>
          </table>
          <p v-if="resolution.last_error" class="cs-error-text">最近错误：{{ resolution.last_error }}</p>
          <p class="cs-hint">结论更新于 {{ formatBeijingTime(resolution.updated_at) }}</p>
        </template>
      </section>

      <form v-if="ticket.status === 'processing'" class="cs-card cs-reply-form" @submit.prevent="replyTicket">
        <h3 class="cs-card-title">答复原客户</h3>
        <p class="cs-hint">发送到原客服会话，保持原工单未解决；答复不代表修复或验收通过。</p>
        <label>客户可见答复<textarea v-model="replyNote" required minlength="4" maxlength="2000" /></label>
        <button class="cs-btn" type="submit" :disabled="saving || savingEta">发送答复并保留原单</button>
      </form>

      <form v-if="ticket.status === 'processing'" class="cs-card cs-close-form" @submit.prevent="closeTicket">
        <h3 class="cs-card-title">处理原工单</h3>
        <p v-if="requiresCustomerAcceptance" class="cs-hint">产品问题与定制交付须由原客户通过运行回执或原工单决策验收；管理员只能按旧单规则记录过期。</p><label v-else>处置方式<select v-model="closeDisposition"><option value="resolved">实际验收已解决</option><option value="expired">已过期不再处理（未修复，不影响资金权益）</option></select></label>
        <label>处理结论<textarea v-model="closeNote" required minlength="8" maxlength="2000" /></label>
        <label>{{ closeDisposition === 'expired' ? '过期与后续活跃需求核对记录' : '实际验收证据' }}<textarea v-model="closeVerification" required minlength="20" maxlength="4000" /></label>
        <button class="cs-btn" type="submit" :disabled="saving || savingEta">记录管理员处置并关闭</button>
      </form>

      <section class="cs-card" aria-label="处理时间线">
        <h3 class="cs-card-title">处理时间线 <span class="cs-count">{{ timeline.length }}</span></h3>
        <p v-if="!timeline.length" class="cs-state">暂无记录</p>
        <ol v-else class="cs-timeline">
          <li v-for="item in timeline" :key="item.key">
            <div class="cs-tl-head">
              <time>{{ formatBeijingTime(item.at) }}</time>
              <span class="cs-tag">{{ item.kind }}</span>
              <strong>{{ item.title }}</strong>
              <span v-for="(b, i) in item.badges" :key="i" class="cs-badge" :class="`is-${b.tone}`" :title="b.raw">{{ b.label }}</span>
            </div>
            <p v-if="item.text" class="cs-tl-text">{{ item.text }}</p>
            <ul v-if="item.team.length" class="cs-chips">
              <li v-for="(m, i) in item.team" :key="i"><span class="cs-badge" :class="`is-${m.status.tone}`">{{ m.role }} · {{ m.status.label }}</span> <code>{{ m.employee }}</code></li>
            </ul>
          </li>
        </ol>
      </section>

      <section class="cs-card" aria-label="审计记录">
        <h3 class="cs-card-title">审计记录 <span class="cs-count">{{ audits.length }}</span></h3>
        <p v-if="!audits.length" class="cs-state">暂无记录</p>
        <div v-else class="cs-table-wrap">
          <table class="cs-table">
            <thead><tr><th>编号</th><th>时间</th><th>操作方</th><th>事件</th><th>摘要</th></tr></thead>
            <tbody>
              <tr v-for="a in audits" :key="a.key">
                <td>#{{ a.id }}</td><td class="cs-time">{{ a.at }}</td><td>{{ a.actor }}</td>
                <td :title="a.eventKey">{{ a.event }}</td><td class="cs-summary">{{ a.summary || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <details class="cs-card cs-raw">
        <summary>原始数据（排查用，默认收起）</summary>
        <p class="cs-hint">包含原单 resolution、附件索引、跟进与员工回写；不展开支持包二进制内容。</p>
        <h4>客户证据、领取与处理进度</h4><pre class="cs-payload">{{ prettyJson(evidence) }}</pre>
        <template v-for="(rows, label) in { 决策记录: detail.decisions, 执行动作: detail.actions, 审计记录: detail.audit_logs }" :key="label">
          <h4>{{ label }}</h4><pre class="cs-payload">{{ rawOrEmpty(rows) }}</pre>
        </template>
      </details>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import api from '@/api/core'
import { appConfirm, appPrompt } from '@/utils/appDialog'
import CustomerServiceSharedRepair from './CustomerServiceSharedRepair.vue'
import {
  auditItems, buildTimeline, executionOverview, formatBeijingTime, intentLabel, parseServerTime, prettyJson, priorityLabel, resolutionStateBadge,
  routeLabel, submitterTypeLabel, teamMembers, ticketStatusBadge, yesNoBadge, type Row,
} from '../utils/customerServiceTicketFormat'

type Detail = { ticket: Row; decisions: Row[]; actions: Row[]; audit_logs: Row[]; execution_overview?: Row }
const route = useRoute()
const router = useRouter()
const detail = ref<Detail | null>(null), loading = ref(false), error = ref(''), saving = ref(false), expectedCompletionInput = ref('')
const savingEta = ref(false), etaMessage = ref(''), etaError = ref('')
const closeNote = ref(''), closeVerification = ref(''), closeRequestId = ref(''), closeDisposition = ref('resolved')
const replyNote = ref(''), replyRequestId = ref('')
watch(replyNote, () => { replyRequestId.value = '' })
let generation = 0

const ticketId = computed(() => Number(String(route.params.ticketId ?? '')))
const validId = computed(() => Number.isInteger(ticketId.value) && ticketId.value > 0)
const ticket = computed<Row>(() => detail.value?.ticket || {})
const canCorrectClassification = computed(() => ticket.value.status === 'processing' && !ticket.value.closed_at && ['account_support', 'general'].includes(String(ticket.value.intent)))
const evidence = computed<Row>(() => Object.fromEntries(Object.entries(
  (ticket.value.evidence || {}) as Row,
).filter(([key]) => key !== 'support_bundle_base64')))
const customDelivery = computed(() => evidence.value.delivery_managed_by === 'custom_delivery' || evidence.value.issue_domain === 'custom' || evidence.value.source === 'private_mod_rework')
const requiresCustomerAcceptance = computed(() => ['product_issue', 'custom_delivery'].includes(String(ticket.value.intent)) || customDelivery.value)
const resolution = computed(() => {
  const value = evidence.value.resolution
  return value && typeof value === 'object' ? value as Row : null
})
const status = computed(() => ticketStatusBadge(ticket.value))
const overview = computed(() => executionOverview(detail.value?.execution_overview))
const steps = computed(() => (Array.isArray(ticket.value.lifecycle_steps) ? ticket.value.lifecycle_steps : []) as Row[])
const resolutionState = computed(() => resolutionStateBadge(resolution.value?.state, resolution.value?.verification_mode))
const repairVerified = computed(() => yesNoBadge(resolution.value?.repair_verified, '修复已验证', '修复未验证'))
const team = computed(() => teamMembers(resolution.value?.team))
const timeline = computed(() => detail.value ? buildTimeline(detail.value.decisions, detail.value.actions, evidence.value) : [])
const audits = computed(() => auditItems(detail.value?.audit_logs || []))
const rawOrEmpty = (rows: unknown[]) => rows.length ? prettyJson(rows) : '暂无记录'
const message = (cause: unknown) => cause instanceof Error ? cause.message : String(cause)

function backToList() { void router.push({ name: 'customer-service-tickets' }) }

watch([closeNote, closeVerification, closeDisposition], () => { closeRequestId.value = '' })
watch([ticketId, requiresCustomerAcceptance], () => { closeDisposition.value = requiresCustomerAcceptance.value ? 'expired' : 'resolved' })

async function replyTicket() {
  const id = ticketId.value
  if (saving.value || savingEta.value || replyNote.value.trim().length < 4 || ticket.value.status !== 'processing') return
  saving.value = true
  try {
    replyRequestId.value ||= crypto.randomUUID()
    await api.post(`/api/xcmax/admin/customer-service/tickets/${id}/reply`, { request_id: replyRequestId.value, note: replyNote.value })
    if (ticketId.value === id) { replyNote.value = ''; replyRequestId.value = ''; await load() }
  } catch (cause) { if (ticketId.value === id) error.value = message(cause) }
  finally { saving.value = false }
}

async function closeTicket() {
  const id = ticketId.value
  if (saving.value || savingEta.value || ticket.value.status !== 'processing') return
  saving.value = true
  try {
    if (!await appConfirm(closeDisposition.value === 'expired' ? '确认已核对过期时间及后续需求？本次记为过期，未修复，不影响资金权益。' : '确认已在目标版本完成实际验收，并关闭这张原工单？', { title: '确认管理员处置', confirmText: '记录并关闭', cancelText: '返回检查', danger: true }) || ticketId.value !== id || ticket.value.status !== 'processing') return
    closeRequestId.value ||= crypto.randomUUID()
    await api.post(`/api/xcmax/admin/customer-service/tickets/${id}/close`, {
      request_id: closeRequestId.value, note: closeNote.value, verification: closeVerification.value,
      disposition: closeDisposition.value,
    })
    if (ticketId.value === id) {
      closeNote.value = ''; closeVerification.value = ''; closeRequestId.value = ''
      await load()
    }
  } catch (cause) { if (ticketId.value === id) error.value = message(cause) }
  finally { saving.value = false }
}

async function correctTitle(reclassify = false) {
  if (saving.value || savingEta.value || (reclassify && !canCorrectClassification.value)) return
  const id = ticketId.value, expectedTitle = String(ticket.value.title || '')
  const title = reclassify ? expectedTitle : (await appPrompt('请输入此工单的正确标题', expectedTitle))?.trim()
  const reason = reclassify ? (await appPrompt('将原单纠正为平台功能问题，保留编号、历史和资金记录。请输入修正原因（至少8字）'))?.trim() : ''
  if (reclassify && reason && reason.length < 8) { error.value = '分类修正原因至少8字，请重新填写'; return }
  if (!title || (!reclassify && title === expectedTitle) || (reclassify && (!reason || reason.length < 8))) return
  saving.value = true
  try {
    await api.put(`/api/xcmax/market-proxy/customer-service/tickets/${id}/title`, {
      title, expected_title: expectedTitle,
      ...(reclassify ? { intent: 'product_issue', expected_intent: ticket.value.intent, reason } : {}),
    })
    if (ticketId.value === id) await load()
  } catch (cause) { if (ticketId.value === id) error.value = message(cause) }
  finally { saving.value = false }
}

function toBeijingInput(value: unknown): string {
  const ms = parseServerTime(value)
  return ms === null ? '' : new Date(ms + 8 * 60 * 60 * 1000).toISOString().slice(0, 16)
}

function fromBeijingInput(value: string): string | null {
  return value ? `${value}:00+08:00` : null
}

async function saveExpectedCompletion() {
  const id = ticketId.value
  if (saving.value || savingEta.value || !validId.value) return
  savingEta.value = true; etaMessage.value = ''; etaError.value = ''
  try {
    await xcmaxAdminApi.updateCustomerTicketExpectedCompletion(id, fromBeijingInput(expectedCompletionInput.value))
    if (ticketId.value !== id) return
    await load()
    if (ticketId.value === id) etaMessage.value = '已保存，客户工单页面会显示此时间。'
  } catch (cause) { if (ticketId.value === id) etaError.value = message(cause) }
  finally { savingEta.value = false }
}

async function clearExpectedCompletion() {
  if (saving.value || savingEta.value) return
  expectedCompletionInput.value = ''
  await saveExpectedCompletion()
}

async function load() {
  const request = ++generation
  detail.value = null; error.value = ''
  if (!validId.value) return
  const id = ticketId.value
  loading.value = true
  try {
    const result = await xcmaxAdminApi.fetchCustomerTicket(id)
    if (request !== generation) return
    if (Number(result.ticket?.id) !== id || !Array.isArray(result.decisions) || !Array.isArray(result.actions) || !Array.isArray(result.audit_logs)) throw new Error('客服详情响应不完整')
    detail.value = result as Detail
    expectedCompletionInput.value = toBeijingInput(result.ticket?.expected_completion_at)
  } catch (cause) { if (request === generation) error.value = message(cause) }
  finally { if (request === generation) loading.value = false }
}
watch(ticketId, () => { replyNote.value = ''; replyRequestId.value = ''; closeDisposition.value = 'resolved'; closeNote.value = ''; closeVerification.value = ''; closeRequestId.value = ''; etaMessage.value = ''; etaError.value = ''; void load() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>

<style scoped src="./CustomerServiceTickets.css"></style>
