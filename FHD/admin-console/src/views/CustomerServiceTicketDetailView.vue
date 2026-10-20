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
            <button type="button" class="cs-btn" :disabled="saving" @click="correctTitle">更正标题</button>
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
          <li v-for="step in steps" :key="step.stage" :class="`is-${step.state}`">{{ step.label }}</li>
        </ol>
        <dl class="cs-facts">
          <div><dt>客户</dt><dd>市场用户 ID {{ ticket.user_id ?? '—' }}<template v-if="ticket.session_id"> · 会话 {{ ticket.session_id }}</template></dd></div>
          <div><dt>提交人身份</dt><dd>{{ submitterTypeLabel(ticket.submitter_type) }}</dd></div>
          <div><dt>指派管理员</dt><dd>{{ ticket.assigned_admin_id || '暂无管理员指派记录' }}</dd></div>
          <div><dt>创建时间</dt><dd>{{ formatBeijingTime(ticket.created_at) }}</dd></div>
          <div><dt>最近更新</dt><dd>{{ formatBeijingTime(ticket.updated_at) }}</dd></div>
          <div><dt>关闭时间</dt><dd>{{ formatBeijingTime(ticket.closed_at, '未关闭') }}</dd></div>
        </dl>
        <p class="cs-hint">时间为北京时间（UTC+8）。处理状态本身不代表员工已领取或执行；以以下真实进度和审计记录为准。</p>
      </section>

      <section class="cs-card">
        <h3 class="cs-card-title">客户问题原文</h3>
        <p class="cs-quote">{{ ticket.summary || '原单未记录正文' }}</p>
      </section>

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

      <form v-if="ticket.status === 'processing'" class="cs-card cs-close-form" @submit.prevent="closeTicket">
        <h3 class="cs-card-title">验收并关闭</h3>
        <label>处理结论<textarea v-model="closeNote" required minlength="8" maxlength="2000" /></label>
        <label>实际验收证据<textarea v-model="closeVerification" required minlength="20" maxlength="4000" /></label>
        <button class="cs-btn" type="submit" :disabled="saving">记录管理员验收并关闭</button>
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
import {
  auditItems, buildTimeline, formatBeijingTime, intentLabel, prettyJson, priorityLabel, resolutionStateBadge,
  routeLabel, submitterTypeLabel, teamMembers, ticketStatusBadge, yesNoBadge, type Row,
} from '../utils/customerServiceTicketFormat'

type Detail = { ticket: Row; decisions: Row[]; actions: Row[]; audit_logs: Row[] }
const route = useRoute()
const router = useRouter()
const detail = ref<Detail | null>(null)
const loading = ref(false), error = ref('')
const saving = ref(false)
const closeNote = ref(''), closeVerification = ref(''), closeRequestId = ref('')
let generation = 0

const ticketId = computed(() => Number(String(route.params.ticketId ?? '')))
const validId = computed(() => Number.isInteger(ticketId.value) && ticketId.value > 0)
const ticket = computed<Row>(() => detail.value?.ticket || {})
const evidence = computed<Row>(() => Object.fromEntries(Object.entries(
  (ticket.value.evidence || {}) as Row,
).filter(([key]) => key !== 'support_bundle_base64')))
const resolution = computed(() => {
  const value = evidence.value.resolution
  return value && typeof value === 'object' ? value as Row : null
})
const status = computed(() => ticketStatusBadge(ticket.value))
const steps = computed(() => (Array.isArray(ticket.value.lifecycle_steps) ? ticket.value.lifecycle_steps : []) as Row[])
const resolutionState = computed(() => resolutionStateBadge(resolution.value?.state))
const repairVerified = computed(() => yesNoBadge(resolution.value?.repair_verified, '修复已验证', '修复未验证'))
const team = computed(() => teamMembers(resolution.value?.team))
const timeline = computed(() => detail.value ? buildTimeline(detail.value.decisions, detail.value.actions, evidence.value) : [])
const audits = computed(() => auditItems(detail.value?.audit_logs || []))
const rawOrEmpty = (rows: unknown[]) => rows.length ? prettyJson(rows) : '暂无记录'
const message = (cause: unknown) => cause instanceof Error ? cause.message : String(cause)

function backToList() { void router.push({ name: 'customer-service-tickets' }) }

watch([closeNote, closeVerification], () => { closeRequestId.value = '' })

async function closeTicket() {
  const id = ticketId.value
  if (saving.value || ticket.value.status !== 'processing' || !window.confirm('确认已在目标版本完成实际验收，并关闭这张原工单？')) return
  closeRequestId.value ||= crypto.randomUUID()
  saving.value = true
  try {
    await api.post(`/api/xcmax/admin/customer-service/tickets/${id}/close`, {
      request_id: closeRequestId.value, note: closeNote.value, verification: closeVerification.value,
    })
    closeNote.value = ''; closeVerification.value = ''; closeRequestId.value = ''
    if (ticketId.value === id) await load()
  } catch (cause) { if (ticketId.value === id) error.value = message(cause) }
  finally { saving.value = false }
}

async function correctTitle() {
  const id = ticketId.value, expectedTitle = String(ticket.value.title || '')
  const title = window.prompt('请输入此工单的正确标题', expectedTitle)?.trim()
  if (!title || title === expectedTitle || saving.value) return
  saving.value = true
  try {
    await api.put(`/api/xcmax/market-proxy/customer-service/tickets/${id}/title`, { title, expected_title: expectedTitle })
    if (ticketId.value === id) await load()
  } catch (cause) { if (ticketId.value === id) error.value = message(cause) }
  finally { saving.value = false }
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
  } catch (cause) { if (request === generation) error.value = message(cause) }
  finally { if (request === generation) loading.value = false }
}
watch(ticketId, () => { void load() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>

<style scoped src="./CustomerServiceTickets.css"></style>
