<template>
  <main class="cs-view page-content admin-screen" id="view-customer-service-ticket-detail">
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
            <span v-if="taxonomy.type" class="cs-tag">{{ taxonomy.type }}</span>
            <span v-if="taxonomy.domain" class="cs-tag">{{ taxonomy.domain }}</span>
            <span v-if="taxonomy.source" class="cs-tag">{{ taxonomy.source }}</span>
            <span v-if="ticket.priority" class="cs-tag">优先级 {{ priorityLabel(ticket.priority) }}</span>
          </div>
        </div>
        <ol v-if="steps.length" class="cs-steps" aria-label="处理阶段">
          <li v-for="step in steps" :key="String(step.stage)" :class="`is-${step.state}`">{{ step.label }}</li>
        </ol>
        <details class="cs-metadata"><summary>客户资料与预计完成时间</summary>
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
        </details>
      </section>

      <AdminSectionNav v-model="section" label="工单详情分区" :items="sections" />
      <div class="admin-pane" tabindex="0" aria-label="工单内容">
      <section v-if="section === 'delivery'" class="cs-card" aria-label="交付进度">
        <template v-if="delivery">
          <ol class="cs-steps" aria-label="交付阶段">
            <li v-for="step in deliverySteps" :key="step.key" :class="deliveryStepClass(step.key)">
              <span>{{ step.label }}</span>
            </li>
          </ol>
          <dl class="cs-facts">
            <div><dt>当前阶段</dt><dd>{{ delivery.stage_label || delivery.stage || '未记录' }}</dd></div>
            <div><dt>客户需求</dt><dd>{{ delivery.requirements || '未提供' }}</dd></div>
            <div><dt>验收标准</dt><dd>{{ delivery.acceptance_criteria || '未提供' }}</dd></div>
            <div><dt>质量门</dt><dd>{{ delivery.gate_ok === true ? '已通过' : '未通过或待运行' }} · {{ delivery.gate_message || '无结果' }}</dd></div>
            <div v-if="latestRun"><dt>最近生产</dt><dd>第 {{ latestRun?.attempt || runCount }} 轮 · {{ runLabel(latestRun?.status) }} · {{ latestRun?.steps?.length || 0 }} 步</dd></div>
            <div><dt>产物</dt><dd>{{ installedCount }}/{{ deliveryArtifacts.length }} 已安装</dd></div>
          </dl>
          <ul v-if="deliveryArtifacts.length" class="cs-chips">
            <li v-for="artifact in deliveryArtifacts" :key="`${artifact.kind}:${artifact.id}`">
              <code>{{ artifact.id }}</code>
              <span class="cs-badge" :class="receiptOf(artifact) ? 'is-success' : 'is-neutral'">{{ receiptOf(artifact) ? `已安装 · ${receiptOf(artifact)?.host || '宿主'}` : '待安装回执' }}</span>
            </li>
          </ul>
          <DeliveryCommercePanel :key="ticketId" :ticket="commerceTicket" @updated="updateDeliveryCommerce" />
          <p v-if="latestRun?.error" class="cs-error-text">{{ latestRun.error }}</p>
          <form class="cs-eta-editor" @submit.prevent>
            <label v-if="canUseMainRework"><input v-model="mainRework" type="checkbox" />使用主线私有模块源码（保留原客户归属与权益）</label>
            <input v-model.trim="reworkNote" type="text" maxlength="4000" placeholder="返工原因（至少 4 个字）" />
            <button class="cs-btn" type="button" :disabled="saving" @click="requestDeliveryRework">发起返工</button>
            <button v-if="canAcceptDelivery" class="cs-btn cs-btn-primary" type="button" :disabled="saving" @click="acceptDelivery">内部质量确认</button>
          </form>
          <p v-if="deliveryError" role="alert" class="cs-error-text">{{ deliveryError }}</p>
        </template>
        <p v-else class="cs-state">暂无交付数据</p>
      </section>
      <section v-if="section === 'github' && ticket.intent === 'product_issue' && !customDelivery" class="cs-card"><TicketGithubPanel :ticket-id="ticketId" :ticket-status="ticket.status" @updated="load" /></section>
      <section v-show="section === 'progress'" class="cs-card">
        <h3 class="cs-card-title">客户问题原文</h3>
        <p class="cs-quote">{{ ticket.summary || '原单未记录正文' }}</p>
        <p v-if="bundleNames.length" class="cs-hint">附件：{{ bundleNames.join('、') }}</p>
        <button v-if="hasBundle" type="button" class="cs-btn" @click="downloadBundle">下载支持包</button>
      </section>

      <section v-show="section === 'handle'" v-if="!ticket.closed_at" class="cs-card" aria-label="人工处理">
        <h3 class="cs-card-title">人工处理</h3>
        <p v-if="handleError" role="alert" class="cs-error-text">{{ handleError }}</p>
        <form class="cs-eta-editor" @submit.prevent="assignHandler()">
          <label>指派给技术管理员 <input v-model="assigneeId" inputmode="numeric" required /></label>
          <label>原因 <input v-model="handleReason" required minlength="4" placeholder="填写操作原因或核对结果" /></label>
          <button class="cs-btn cs-btn-primary" type="submit" :disabled="saving">指派</button>
          <button class="cs-btn" type="button" :disabled="saving" @click="assignHandler(true)">指派给我</button>
          <button class="cs-btn" type="button" :disabled="saving" @click="acceptHandler">受理</button>
          <button class="cs-btn" type="button" :disabled="saving" @click="diagnoseHandler">记录诊断</button>
        </form>
        <form class="cs-eta-editor" @submit.prevent="requestSensitive">
          <label>敏感操作 <input v-model="sensitiveChange" placeholder="例如 调整客户可见配置" required /></label>
          <button class="cs-btn" type="submit" :disabled="saving">申请审批</button>
          <button class="cs-btn" type="button" :disabled="saving || !sensitiveActionId" @click="decideSensitive('approved')">批准并执行</button>
          <button class="cs-btn" type="button" :disabled="saving || !sensitiveActionId" @click="decideSensitive('rejected')">拒绝</button>
        </form>
        <form class="cs-eta-editor" @submit.prevent="submitResult(false)">
          <button class="cs-btn" type="button" :disabled="saving" @click="submitResult(true)">故障仍在，不能结案</button>
          <button class="cs-btn cs-btn-primary" type="submit" :disabled="saving">复测通过，待客户确认</button>
        </form>
      </section>

      <section v-show="section === 'progress'" class="cs-card" aria-label="执行总览">
        <h3 class="cs-card-title">执行总览</h3>
        <p v-if="!overview" class="cs-state">暂无记录</p>
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
          <p v-if="!overview.receipts.length" class="cs-hint">当前事件尚无可核验的任务派发回执。</p>
          <ul v-else class="cs-chips" aria-label="派发与执行凭证">
            <li v-for="receipt in overview.receipts" :key="receipt.key">
              {{ receipt.kind }} · {{ receipt.role }} · <code>{{ receipt.taskId }}</code>
              <span class="cs-badge" :class="`is-${receipt.badge.tone}`">{{ receipt.badge.label }}</span>
              · 领取：{{ receipt.claim }} · 执行：{{ receipt.execution }}
            </li>
          </ul>
        </template>
      </section>

      <CustomerServiceSharedRepair v-show="section === 'handle'" v-if="ticket.status === 'processing' && ticket.intent === 'product_issue' && !customDelivery"
        :key="ticketId" :ticket-id="ticketId" @linked="load" />

      <section v-show="section === 'progress'" class="cs-card">
        <h3 class="cs-card-title">处理结论</h3>
        <template v-if="disposition">
          <dl class="cs-facts">
            <div><dt>工单处置</dt><dd>{{ dispositionLabel(disposition.kind) }}</dd></div>
            <div><dt>客户答复</dt><dd>{{ disposition.note }}</dd></div>
            <div><dt>核对证据</dt><dd>{{ disposition.verification }}</dd></div>
            <div><dt>处置时间</dt><dd>{{ formatBeijingTime(disposition.at) }}</dd></div>
            <div><dt>执行状态</dt><dd>{{ executionStopLabel((disposition.execution_stop as Row | undefined)?.state) }}</dd></div>
          </dl>
        </template>
        <p v-else-if="!resolution" class="cs-state">暂无处理结论记录</p>
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

      <form v-show="section === 'handle'" v-if="ticket.status === 'processing' && !ticket.closed_at" class="cs-card cs-reply-form" @submit.prevent="replyTicket">
        <h3 class="cs-card-title">答复原客户</h3>
        <label>客户可见答复<textarea v-model="replyNote" required minlength="4" maxlength="2000" /></label>
        <button class="cs-btn" type="submit" :disabled="saving || savingEta">发送答复并保留原单</button>
      </form>

      <form v-show="section === 'handle'" v-if="ticket.status === 'processing' && !ticket.closed_at" class="cs-card cs-close-form" @submit.prevent="closeTicket">
        <h3 class="cs-card-title">处理原工单</h3>
        <label v-if="closeOptions.length > 1">处置方式
          <select v-model="closeDisposition">
            <option v-for="option in closeOptions" :key="option" :value="option">{{ dispositionLabel(option) }}</option>
          </select>
        </label>
        <p v-if="isDismissal(closeDisposition)" class="cs-hint">先以当前管理员身份受理并记录诊断。处置结论会发回原客服会话，已派发任务的停止状态以后台回执为准。</p>
        <label>处理结论<textarea v-model="closeNote" required minlength="8" maxlength="2000" /></label>
        <label>{{ closeVerificationLabel }}<textarea v-model="closeVerification" required minlength="20" maxlength="4000" /></label>
        <button class="cs-btn" type="submit" :disabled="saving || savingEta">{{ isDismissal(closeDisposition) ? '记录处置并驳回' : '记录管理员处置并关闭' }}</button>
      </form>

      <section v-show="section === 'history'" class="cs-card" aria-label="处理时间线">
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

      <section v-show="section === 'history'" class="cs-card" aria-label="审计记录">
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

      <details v-show="section === 'evidence'" open class="cs-card cs-raw">
        <summary>原始数据</summary>
        <h4>客户证据、领取与处理进度</h4><pre class="cs-payload">{{ prettyJson(evidence) }}</pre>
        <template v-for="(rows, label) in { 决策记录: detail.decisions, 执行动作: detail.actions, 审计记录: detail.audit_logs }" :key="label">
          <h4>{{ label }}</h4><pre class="cs-payload">{{ rawOrEmpty(rows) }}</pre>
        </template>
      </details>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import AdminSectionNav from '../components/admin/AdminSectionNav.vue'
const section = ref('progress')
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { xcmaxAdminApi, type CustomDeliveryTicket } from '@/api/xcmaxAdmin'
import api from '@/api/core'
import { appConfirm, appPrompt } from '@/utils/appDialog'
import DeliveryCommercePanel from '../components/admin/DeliveryCommercePanel.vue'
import CustomerServiceSharedRepair from './CustomerServiceSharedRepair.vue'
import TicketGithubPanel from '../components/workflow/TicketGithubPanel.vue'
import {
  auditItems, buildTimeline, dispositionLabel, executionOverview, executionStopLabel, formatBeijingTime, parseServerTime, prettyJson, priorityLabel, resolutionStateBadge,
  routeLabel, submitterTypeLabel, teamMembers, ticketDomainLabel, ticketSourceLabel, ticketStatusBadge, ticketTypeLabel, yesNoBadge, type Row,
} from '../utils/customerServiceTicketFormat'
import { addonTimelineSteps, initialTimelineSteps } from '../utils/deliveryPresentation'

type Detail = { ticket: Row; decisions: Row[]; actions: Row[]; audit_logs: Row[]; execution_overview?: Row; custom_delivery?: Row }
const route = useRoute()
const router = useRouter()
const detail = ref<Detail | null>(null), loading = ref(false), error = ref(''), saving = ref(false), expectedCompletionInput = ref('')
const savingEta = ref(false), etaMessage = ref(''), etaError = ref('')
type CloseDisposition = 'resolved' | 'expired' | 'invalid' | 'out_of_scope'
const closeNote = ref(''), closeVerification = ref(''), closeRequestId = ref(''), closeDisposition = ref<CloseDisposition>('resolved')
const replyNote = ref(''), replyRequestId = ref('')
const assigneeId = ref(''), handleReason = ref(''), handleError = ref('')
const sensitiveChange = ref('调整客户可见配置'), sensitiveActionId = ref(0)
const reworkNote = ref(''), deliveryError = ref(''), mainRework = ref(false)
const canUseMainRework = computed(() => detail.value?.custom_delivery?.kind === 'module' && detail.value?.custom_delivery?.suggested_id === 'sunbird-attendance-custom')
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
const delivery = computed<Row | null>(() => {
  const value = detail.value?.custom_delivery
  return value && typeof value === 'object' ? value as Row : null
})
const commerceTicket = computed<CustomDeliveryTicket>(() => ({ ...ticket.value, id: ticketId.value, custom_delivery: delivery.value || undefined }))
function updateDeliveryCommerce(updated: CustomDeliveryTicket) {
  if (updated.id === ticketId.value && detail.value) detail.value.custom_delivery = updated.custom_delivery
}
const sections = computed(() => [
  { value: 'progress', label: '问题与进度' },
  ...(delivery.value ? [{ value: 'delivery', label: '交付进度' }] : []),
  { value: 'github', label: 'GitHub 修复' },
  { value: 'handle', label: '人工处理' },
  { value: 'history', label: '时间线与审计' },
  { value: 'evidence', label: '原始证据' },
])
const taxonomy = computed(() => ({
  type: ticketTypeLabel(ticket.value), domain: ticketDomainLabel(ticket.value), source: ticketSourceLabel(ticket.value),
}))
const closeOptions = computed<CloseDisposition[]>(() => {
  if (ticket.value.intent === 'custom_delivery' || customDelivery.value) return ['expired']
  return ticket.value.intent === 'product_issue'
    ? ['expired', 'invalid', 'out_of_scope']
    : ['resolved', 'expired', 'invalid', 'out_of_scope']
})
const isDismissal = (value: CloseDisposition) => value === 'invalid' || value === 'out_of_scope'
const closeVerificationLabel = computed(() => ({
  resolved: '实际验收证据', expired: '过期与后续活跃需求核对记录',
  invalid: '无效原因的核对证据', out_of_scope: '超出服务范围的核对证据',
})[closeDisposition.value])
const disposition = computed(() => ticket.value.disposition && typeof ticket.value.disposition === 'object'
  ? ticket.value.disposition as Row : null)
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
const hasBundle = computed(() => Boolean((ticket.value.evidence as Row | undefined)?.support_bundle_base64))
const bundleNames = computed(() => {
  const names = (ticket.value.evidence as Row | undefined)?.customerLogs
  return Array.isArray(names) ? names.map(String) : []
})

function downloadBundle() {
  const raw = String((ticket.value.evidence as Row | undefined)?.support_bundle_base64 || '')
  if (!raw) { handleError.value = '无可下载支持包'; return }
  const bytes = Uint8Array.from(atob(raw), (ch) => ch.charCodeAt(0))
  const url = URL.createObjectURL(new Blob([bytes], { type: 'application/zip' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${ticket.value.ticket_no || ticketId.value}-support.zip`
  link.click()
  URL.revokeObjectURL(url)
}

const deliverySteps = computed(() => delivery.value?.pricing_mode === 'post_delivery_addon' ? addonTimelineSteps : initialTimelineSteps)
const latestRun = computed<Row | null>(() => {
  const runs = Array.isArray(delivery.value?.runs) ? delivery.value!.runs as Row[] : []
  return runs.length ? runs[runs.length - 1] : null
})
const installedCount = computed(() => (Array.isArray(delivery.value?.install_receipts) ? delivery.value!.install_receipts as Row[] : []).length)
const runCount = computed(() => Array.isArray(delivery.value?.runs) ? delivery.value!.runs.length : 0)
const deliveryArtifacts = computed<Row[]>(() => Array.isArray(delivery.value?.artifacts) ? delivery.value!.artifacts as Row[] : [])
const canAcceptDelivery = computed(() => String(delivery.value?.stage || '') === 'acceptance'
  && delivery.value?.gate_ok === true && String(delivery.value?.acceptance_status || 'pending') === 'pending')

function receiptOf(artifact: Row): Row | undefined {
  const receipts = Array.isArray(delivery.value?.install_receipts) ? delivery.value!.install_receipts as Row[] : []
  return receipts.find((row) => row.kind === artifact.kind && row.id === artifact.id)
}
const runLabel = (status: unknown) => ({ done: '完成', running: '运行中', queued: '排队中', error: '失败' } as Record<string, string>)[String(status || '')] || '未知'
function stageRank(stage: string) {
  return deliverySteps.value.findIndex((step) => step.key === (stage === 'rework' ? 'production' : stage))
}
function deliveryStepClass(key: string) {
  const stage = String(delivery.value?.stage || '')
  const rank = stageRank(stage)
  const stepRank = stageRank(key)
  return {
    'is-done': stepRank < rank || stage === 'delivered',
    'is-current': stepRank === rank && stage !== 'rework',
    'is-failed': stage === 'rework' && key === 'production',
  }
}

async function acceptDelivery() {
  if (!canAcceptDelivery.value || saving.value) return
  const id = ticketId.value, currentGeneration = generation
  if (!await appConfirm(`确认工单 ${ticket.value.ticket_no || ticketId.value} 通过内部质量检查？`, { title: '内部质量确认', confirmText: '确认质量通过' })) return
  if (id !== ticketId.value || currentGeneration !== generation || saving.value) return
  saving.value = true; deliveryError.value = ''
  try {
    await xcmaxAdminApi.decideCustomDelivery(id, 'accept', '管理员仅完成内部质量确认，等待客户本人验收')
    if (id === ticketId.value && currentGeneration === generation) await load()
  } catch (cause) { if (id === ticketId.value && currentGeneration === generation) deliveryError.value = apiError(cause) }
  finally { saving.value = false }
}

async function requestDeliveryRework() {
  if (saving.value) return
  const id = ticketId.value, currentGeneration = generation
  const note = reworkNote.value.trim()
  const useMain = mainRework.value && canUseMainRework.value
  if (note.length < 4) { deliveryError.value = '返工原因至少 4 个字'; return }
  if (!await appConfirm(`将工单 ${ticket.value.ticket_no || ticketId.value} 发回重新执行？`, { title: '发起返工', confirmText: '确认返工' })) return
  if (id !== ticketId.value || currentGeneration !== generation || saving.value) return
  saving.value = true; deliveryError.value = ''
  try {
    if (useMain) await xcmaxAdminApi.decideCustomDelivery(id, 'rework', note, 'versioned_main')
    else await xcmaxAdminApi.decideCustomDelivery(id, 'rework', note)
    if (id === ticketId.value && currentGeneration === generation) { reworkNote.value = ''; await load() }
  } catch (cause) { if (id === ticketId.value && currentGeneration === generation) deliveryError.value = apiError(cause) }
  finally { saving.value = false }
}

async function postHandle(command: string, body: Row, assignToMe = false) {
  const id = ticketId.value, started = generation
  if (!validId.value || saving.value || savingEta.value || ticket.value.closed_at) return
  handleError.value = ''
  if (handleReason.value.trim().length < 4) {
    handleError.value = '请填写至少 4 字的操作原因'
    return
  }
  saving.value = true
  try {
    if (assignToMe) {
      const staff = await api.get<Row>('/api/xcmax/admin/customer-service/staff')
      const viewerId = Number(staff?.viewer_id)
      if (id !== ticketId.value || started !== generation) return
      if (!Number.isSafeInteger(viewerId) || viewerId <= 0) throw new Error('当前管理员身份不可核验')
      body.assignee_id = viewerId
    }
    await api.post(`/api/xcmax/admin/customer-service/tickets/${id}/${command}`, body)
    if (id === ticketId.value && started === generation) await load()
  } catch (err) {
    if (id === ticketId.value && started === generation) handleError.value = apiError(err)
  } finally {
    saving.value = false
  }
}

function assignHandler(assignToMe = false) {
  return postHandle('assign', { assignee_id: Number(assigneeId.value), reason: handleReason.value }, assignToMe)
}
function acceptHandler() { return postHandle('accept', { reason: handleReason.value }) }
function diagnoseHandler() { return postHandle('diagnose', { reason: handleReason.value }) }
function requestSensitive() {
  return postHandle('sensitive-action', { change: sensitiveChange.value, reason: handleReason.value })
}
function decideSensitive(decision: 'approved' | 'rejected') {
  return postHandle('sensitive-action/decision', { action_id: sensitiveActionId.value, decision, reason: handleReason.value })
}
function submitResult(faultRemains: boolean) {
  return postHandle('result', { text: handleReason.value, fault_remains: faultRemains })
}
const audits = computed(() => auditItems(detail.value?.audit_logs || []))
const rawOrEmpty = (rows: unknown[]) => rows.length ? prettyJson(rows) : '暂无记录'
const message = (cause: unknown) => cause instanceof Error ? cause.message : String(cause)
function apiError(cause: unknown) {
  const detail = (cause as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  return message(cause)
}

function backToList() { void router.push({ name: 'customer-service-tickets' }) }

watch([closeNote, closeVerification, closeDisposition], () => { closeRequestId.value = '' })
watch(closeOptions, options => {
  if (!closeRequestId.value && !options.includes(closeDisposition.value)) closeDisposition.value = options[0]
})

async function replyTicket() {
  const id = ticketId.value, started = generation
  if (saving.value || savingEta.value || replyNote.value.trim().length < 4 || ticket.value.status !== 'processing' || ticket.value.closed_at) return
  saving.value = true
  try {
    replyRequestId.value ||= crypto.randomUUID()
    await api.post(`/api/xcmax/admin/customer-service/tickets/${id}/reply`, { request_id: replyRequestId.value, note: replyNote.value })
    if (ticketId.value === id && started === generation) { replyNote.value = ''; replyRequestId.value = ''; await load() }
  } catch (cause) { if (ticketId.value === id && started === generation) error.value = apiError(cause) }
  finally { saving.value = false }
}

async function closeTicket() {
  const id = ticketId.value, started = generation
  const selected = closeDisposition.value, note = closeNote.value, verification = closeVerification.value
  if (saving.value || savingEta.value || ticket.value.status !== 'processing' || ticket.value.closed_at
    || !closeOptions.value.includes(selected) || note.trim().length < 8 || verification.trim().length < 20) return
  const dismissing = isDismissal(selected)
  const question = dismissing
    ? `确认将工单 ${ticket.value.ticket_no || id} 标记为「${dispositionLabel(selected)}」并将结论发回原客服会话？`
    : selected === 'expired'
      ? '确认已核对过期时间及后续需求？本次记为过期，未修复，不影响资金权益。'
      : '确认已在目标版本完成实际验收，并关闭这张原工单？'
  saving.value = true
  try {
    if (!await appConfirm(question, { title: '确认管理员处置', confirmText: '记录并关闭', cancelText: '返回检查', danger: true })
      || id !== ticketId.value || started !== generation || selected !== closeDisposition.value
      || note !== closeNote.value || verification !== closeVerification.value) return
    closeRequestId.value ||= crypto.randomUUID()
    await api.post(`/api/xcmax/admin/customer-service/tickets/${id}/${dismissing ? 'disposition' : 'close'}`, {
      request_id: closeRequestId.value, note, verification, disposition: selected,
    })
    if (id === ticketId.value && started === generation) {
      closeNote.value = ''; closeVerification.value = ''; closeRequestId.value = ''
      await load()
    }
  } catch (cause) { if (id === ticketId.value && started === generation) error.value = apiError(cause) }
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
    if (ticketId.value === id) etaMessage.value = '已保存'
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
    const pending = [...(result.actions || [])].reverse().find((row) => row.action_type === 'ticket.apply_change' && row.status === 'waiting_approval')
    sensitiveActionId.value = pending ? Number(pending.id || 0) : 0
    expectedCompletionInput.value = toBeijingInput(result.ticket?.expected_completion_at)
  } catch (cause) { if (request === generation) error.value = message(cause) }
  finally { if (request === generation) loading.value = false }
}
watch(ticketId, () => {
  reworkNote.value = ''; mainRework.value = false; deliveryError.value = ''
  assigneeId.value = ''; handleReason.value = ''; handleError.value = ''
  replyNote.value = ''; replyRequestId.value = ''
  closeDisposition.value = 'resolved'; closeNote.value = ''; closeVerification.value = ''; closeRequestId.value = ''
  etaMessage.value = ''; etaError.value = ''; void load()
}, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>

<style scoped src="./CustomerServiceTickets.css"></style>
<style scoped>
.cs-steps li.is-failed { color: #b91c1c; }
.cs-steps li.is-failed::before { background: #dc2626; color: #fff; }
</style>
