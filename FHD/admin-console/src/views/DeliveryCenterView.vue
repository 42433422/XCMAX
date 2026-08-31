<template>
  <div class="delivery-center page-content" id="view-delivery-center">
    <header class="delivery-hero">
      <div>
        <p class="delivery-eyebrow">CUSTOMER DELIVERY CONTROL</p>
        <h2>客户交付中心</h2>
        <p>所有企业用户统一进入交付台账；内部本 Mac 永不计入客户交付；购买权益、定制路径、安装与首次登录证据分别如实展示。</p>
      </div>
      <button type="button" class="delivery-refresh" :disabled="loading" @click="loadAll">
        <i class="fa fa-refresh" :class="{ 'fa-spin': loading }" aria-hidden="true"></i>
        {{ loading ? '同步中…' : '同步交付状态' }}
      </button>
    </header>

    <section class="delivery-stats" aria-label="交付统计">
      <article v-for="item in summaryCards" :key="item.key" :class="`is-${item.key}`">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.hint }}</small>
      </article>
    </section>

    <EnterpriseCustomerRoster
      v-if="!errorMessage && (!loading || enterpriseUsers.length)"
      :users="enterpriseUsers"
      :tickets="tickets"
      :permanent-deliveries="standardDeliveries"
      :trial-deliveries="trialDeliveries"
      @open-custom="focusCustomDeliveries"
    />

    <EnterpriseDeliveryRoster
      v-if="!errorMessage && (!loading || standardDeliveries.length)"
      :deliveries="standardDeliveries"
      :tickets="tickets"
      :policy="standardPolicy"
      @open-custom="focusCustomDeliveries"
    />

    <EnterpriseDeliveryRoster
      v-if="!errorMessage && (!loading || trialDeliveries.length)"
      variant="trial"
      :deliveries="trialDeliveries"
      :tickets="tickets"
      :policy="trialPolicy"
      @open-custom="focusCustomDeliveries"
    />

    <section id="delivery-custom-orders" class="delivery-toolbar" aria-label="定制交付工单筛选">
      <label>
        <i class="fa fa-search" aria-hidden="true"></i>
        <input v-model.trim="query" type="search" placeholder="搜索客户、工单号或需求名称" />
      </label>
      <select v-model="stageFilter" aria-label="按交付阶段筛选">
        <option value="">全部阶段</option>
        <option v-for="item in stageOptions" :key="item.value" :value="item.value">
          {{ item.label }}
        </option>
      </select>
      <span>定制工单 {{ filteredTickets.length }} / {{ tickets.length }} 项</span>
    </section>

    <div v-if="errorMessage" class="delivery-alert" role="alert">
      <i class="fa fa-exclamation-circle" aria-hidden="true"></i>
      <div>
        <strong>交付数据暂时无法读取</strong>
        <p>{{ errorMessage }}</p>
      </div>
      <button type="button" @click="loadAll">重试</button>
    </div>

    <div v-else-if="loading && !tickets.length && !enterpriseUsers.length && !standardDeliveries.length" class="delivery-empty">
      <i class="fa fa-circle-o-notch fa-spin" aria-hidden="true"></i>
      <strong>正在汇总客户交付证据</strong>
      <span>会同时读取客户身份、生产运行、质量门和安装回执。</span>
    </div>

    <div v-else-if="!filteredTickets.length" class="delivery-empty">
      <i class="fa fa-inbox" aria-hidden="true"></i>
      <strong>{{ tickets.length ? '没有符合筛选条件的定制工单' : '暂无定制交付工单' }}</strong>
      <span>无需定制的企业用户仍在上方企业客户台账中；首次交付后新增需求才进入报价付款。</span>
    </div>

    <section v-else class="delivery-list" aria-label="客户交付列表">
      <article v-for="ticket in filteredTickets" :key="ticket.id" class="delivery-ticket">
        <header class="delivery-ticket__head">
          <div class="delivery-customer">
            <span class="delivery-customer__avatar">{{ customerInitial(ticket) }}</span>
            <div>
              <div class="delivery-customer__line">
                <strong>{{ customerName(ticket) }}</strong>
                <span>{{ kindLabel(ticket.custom_delivery?.kind) }}</span>
                <span>{{ ticket.custom_delivery?.pricing_label || '交付规则待识别' }}</span>
                <span :class="`stage-tag is-${stageOf(ticket)}`">
                  {{ ticket.custom_delivery?.stage_label || stageLabel(stageOf(ticket)) }}
                </span>
              </div>
              <p>{{ ticket.title || '未命名交付' }}</p>
            </div>
          </div>
          <div class="delivery-ticket__meta">
            <span>{{ ticket.ticket_no || `#${ticket.id}` }}</span>
            <time>{{ formatDate(ticket.updated_at || ticket.created_at) }}</time>
          </div>
        </header>

        <ol class="delivery-timeline" aria-label="交付阶段">
          <li
            v-for="step in timelineStepsFor(ticket)"
            :key="step.key"
            :class="timelineClass(ticket, step.key)"
          >
            <span><i :class="`fa ${step.icon}`" aria-hidden="true"></i></span>
            <div><strong>{{ step.label }}</strong><small>{{ step.hint }}</small></div>
          </li>
        </ol>

        <div class="delivery-ticket__body">
          <section class="delivery-brief">
            <div>
              <h3>客户需求</h3>
              <p>{{ ticket.custom_delivery?.requirements || '未提供需求说明' }}</p>
            </div>
            <div>
              <h3>验收标准</h3>
              <p>{{ ticket.custom_delivery?.acceptance_criteria || '未提供验收标准' }}</p>
            </div>
          </section>

          <aside class="delivery-proof">
            <div class="delivery-gate" :class="gateClass(ticket)">
              <i :class="`fa ${gateIcon(ticket)}`" aria-hidden="true"></i>
              <div>
                <strong>{{ gateTitle(ticket) }}</strong>
                <span>{{ ticket.custom_delivery?.gate_message || '等待生产运行提供质量证据' }}</span>
              </div>
            </div>

            <div v-if="latestRun(ticket)" class="delivery-run">
              <div><span>最近生产</span><strong>第 {{ latestRun(ticket)?.attempt || runCount(ticket) }} 轮</strong></div>
              <div><span>运行状态</span><strong>{{ runStatusLabel(latestRun(ticket)?.status) }}</strong></div>
              <div><span>执行步骤</span><strong>{{ latestRun(ticket)?.steps?.length || 0 }} 项</strong></div>
              <p v-if="latestRun(ticket)?.error" class="delivery-run__error">
                {{ latestRun(ticket)?.error }}
              </p>
            </div>
          </aside>
        </div>

        <section class="delivery-artifacts">
          <header>
            <h3>产物与安装回执</h3>
            <span>{{ installedArtifactCount(ticket) }}/{{ artifactCount(ticket) }} 已安装</span>
          </header>
          <div v-if="artifactCount(ticket)" class="delivery-artifact-list">
            <div v-for="artifact in ticket.custom_delivery?.artifacts || []" :key="`${artifact.kind}:${artifact.id}`">
              <i :class="`fa ${artifact.kind === 'employee' ? 'fa-user-circle' : 'fa-cube'}`" aria-hidden="true"></i>
              <div>
                <strong>{{ artifact.kind === 'employee' ? 'AI 员工包' : '业务模块' }}</strong>
                <code>{{ artifact.id }}</code>
              </div>
              <span v-if="receiptFor(ticket, artifact.kind, artifact.id)" class="receipt is-installed">
                已安装 · {{ receiptFor(ticket, artifact.kind, artifact.id)?.host || 'XCAGI' }}
              </span>
              <span v-else class="receipt">待客户安装回执</span>
            </div>
          </div>
          <p v-else class="delivery-artifacts__empty">生产尚未形成可交付产物。</p>
        </section>

        <DeliveryCommercePanel :ticket="ticket" @updated="updateDeliveryTicket" />

        <footer class="delivery-actions">
          <div class="delivery-actions__note">
            <i class="fa fa-shield" aria-hidden="true"></i>
            <span>内部确认不会冒充客户验收；不把“已生成”冒充“已安装”。</span>
          </div>
          <div v-if="stageOf(ticket) !== 'delivered'" class="delivery-actions__controls">
            <input
              v-model.trim="reworkNotes[ticket.id]"
              type="text"
              maxlength="4000"
              placeholder="需要返工时填写具体原因（至少 4 个字）"
            />
            <button
              type="button"
              class="action-secondary"
              :disabled="busyTicketId === ticket.id"
              @click="requestRework(ticket)"
            >
              发起返工
            </button>
            <button
              v-if="canAccept(ticket)"
              type="button"
              class="action-primary"
              :disabled="busyTicketId === ticket.id"
              @click="acceptDelivery(ticket)"
            >
              内部质量确认
            </button>
          </div>
          <strong v-else class="delivery-complete">
            <i class="fa fa-check-circle" aria-hidden="true"></i> 交付闭环完成
          </strong>
        </footer>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import DeliveryCommercePanel from '../components/admin/DeliveryCommercePanel.vue'
import EnterpriseCustomerRoster from '../components/admin/EnterpriseCustomerRoster.vue'
import EnterpriseDeliveryRoster from '../components/admin/EnterpriseDeliveryRoster.vue'
import {
  xcmaxAdminApi,
  type CustomDeliveryArtifact,
  type CustomDeliveryRun,
  type CustomDeliveryTicket,
  type MarketAdminUser,
  type StandardDeliveryPolicy,
  type StandardDeliveryRecord,
} from '@/api/xcmaxAdmin'
import { addonTimelineSteps, initialTimelineSteps, stageOptions } from '../utils/deliveryCenterTimeline'
import { fetchAllEnterpriseUsers } from '../utils/deliveryEnterpriseRoster'
import { appAlert, appConfirm } from '@/utils/appDialog'

const tickets = ref<CustomDeliveryTicket[]>([])
const enterpriseUsers = ref<MarketAdminUser[]>([])
const standardDeliveries = ref<StandardDeliveryRecord[]>([])
const trialDeliveries = ref<StandardDeliveryRecord[]>([])
const standardPolicy = ref<StandardDeliveryPolicy>({})
const trialPolicy = ref<StandardDeliveryPolicy>({})
const usersById = ref(new Map<number, MarketAdminUser>())
const query = ref('')
const stageFilter = ref('')
const loading = ref(false)
const errorMessage = ref('')
const busyTicketId = ref<number | null>(null)
const reworkNotes = reactive<Record<number, string>>({})

const filteredTickets = computed(() => {
  const needle = query.value.toLowerCase()
  return tickets.value.filter((ticket) => {
    const stage = stageOf(ticket)
    if (stageFilter.value && stage !== stageFilter.value) return false
    if (!needle) return true
    return [
      customerName(ticket),
      ticket.ticket_no,
      ticket.title,
      ticket.custom_delivery?.requirements,
    ].some((value) => String(value || '').toLowerCase().includes(needle))
  })
})

const summaryCards = computed(() => {
  const count = (stages: string[]) => tickets.value.filter((ticket) => stages.includes(stageOf(ticket))).length
  return [
    { key: 'enterprise', label: '企业用户', value: enterpriseUsers.value.length, hint: '全部渲染企业卡片' },
    { key: 'permanent', label: '永久购买账户', value: standardDeliveries.value.length, hint: '来源：购买账户 SSOT' },
    { key: 'trial', label: '体验账户', value: trialDeliveries.value.length, hint: '¥99 · 30 天全功能体验' },
    { key: 'standard', label: '永久待安装', value: standardDeliveries.value.filter((row) => row.status === 'pending_install').length, hint: 'Mac / Windows 通用安装包' },
    { key: 'receipt', label: '待首次登录', value: standardDeliveries.value.filter((row) => row.status === 'pending_first_login').length, hint: '安装成功，等待账号登录' },
    { key: 'done', label: '永久交付完成', value: standardDeliveries.value.filter((row) => row.status === 'completed').length, hint: '客户设备安装 + 首次登录' },
    { key: 'internal', label: '内部本机排除', value: standardPolicy.value.internal_device_ids_configured || 0, hint: standardPolicy.value.internal_device_exclusion_enabled ? '已登记，不计客户交付' : '尚未登记内部设备' },
    { key: 'custom', label: '定制交付工单', value: tickets.value.length, hint: '首次内含 / 交付后新增' },
    { key: 'production', label: '生产进行中', value: count(['queued', 'production']), hint: '等待产物与质量证据' },
  ]
})

function extractTickets(raw: unknown): CustomDeliveryTicket[] {
  const body = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const nested = body.data && typeof body.data === 'object' ? body.data as Record<string, unknown> : {}
  const rows = Array.isArray(body.items) ? body.items : Array.isArray(nested.items) ? nested.items : []
  return rows as CustomDeliveryTicket[]
}

function extractStandardDeliveries(raw: unknown): StandardDeliveryRecord[] {
  const body = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const nested = body.data && typeof body.data === 'object' ? body.data as Record<string, unknown> : {}
  const rows = Array.isArray(body.items) ? body.items : Array.isArray(nested.items) ? nested.items : []
  return rows as StandardDeliveryRecord[]
}

function extractStandardPolicy(raw: unknown): StandardDeliveryPolicy {
  const body = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const nested = body.data && typeof body.data === 'object' ? body.data as Record<string, unknown> : {}
  const policy = body.policy && typeof body.policy === 'object'
    ? body.policy
    : nested.policy && typeof nested.policy === 'object' ? nested.policy : {}
  return policy as StandardDeliveryPolicy
}

async function loadAll() {
  loading.value = true
  errorMessage.value = ''
  try {
    const [deliveryResult, enterpriseAccounts, standardResult, trialResult] = await Promise.all([
      xcmaxAdminApi.listCustomDeliveries(100),
      fetchAllEnterpriseUsers(),
      xcmaxAdminApi.listStandardDeliveries(),
      xcmaxAdminApi.listTrialDeliveries(),
    ])
    tickets.value = extractTickets(deliveryResult)
    enterpriseUsers.value = enterpriseAccounts
    standardDeliveries.value = extractStandardDeliveries(standardResult)
    trialDeliveries.value = extractStandardDeliveries(trialResult)
    standardPolicy.value = extractStandardPolicy(standardResult)
    trialPolicy.value = extractStandardPolicy(trialResult)
    usersById.value = new Map(
      [
        ...enterpriseAccounts,
        ...standardDeliveries.value.map((row) => row.account),
        ...trialDeliveries.value.map((row) => row.account),
      ].map((account) => [Number(account.id), account]),
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function focusCustomDeliveries(user: MarketAdminUser) {
  query.value = String(user.company || user.username || '')
  stageFilter.value = ''
  await nextTick()
  document.getElementById('delivery-custom-orders')?.scrollIntoView({ behavior: 'smooth' })
}

function stageOf(ticket: CustomDeliveryTicket): string {
  return String(ticket.custom_delivery?.stage || 'queued')
}

function stageLabel(stage: string): string {
  return stageOptions.find((item) => item.value === stage)?.label || stage
}

function kindLabel(kind?: string): string {
  return ({ module: '业务模块', employee: 'AI 员工', bundle: '模块 + AI 员工' } as Record<string, string>)[String(kind || '')] || '定制交付'
}

function customer(ticket: CustomDeliveryTicket): MarketAdminUser | undefined {
  return ticket.user_id == null ? undefined : usersById.value.get(Number(ticket.user_id))
}

function customerName(ticket: CustomDeliveryTicket): string {
  const row = customer(ticket)
  return String(row?.company || row?.username || (ticket.user_id ? `客户 #${ticket.user_id}` : '未知客户'))
}

function customerInitial(ticket: CustomDeliveryTicket): string {
  return customerName(ticket).slice(0, 1).toUpperCase()
}

function formatDate(value?: string): string {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function timelineStepsFor(ticket: CustomDeliveryTicket) {
  return ticket.custom_delivery?.pricing_mode === 'post_delivery_addon'
    ? addonTimelineSteps
    : initialTimelineSteps
}

function stageRank(ticket: CustomDeliveryTicket, stage: string): number {
  const normalized = stage === 'rework' ? 'production' : stage
  const index = timelineStepsFor(ticket).findIndex((step) => step.key === normalized)
  return index < 0 ? 0 : index
}

function updateDeliveryTicket(updated: CustomDeliveryTicket) {
  const index = tickets.value.findIndex((row) => row.id === updated.id)
  if (index >= 0) tickets.value[index] = updated
}

function timelineClass(ticket: CustomDeliveryTicket, step: string): Record<string, boolean> {
  const stage = stageOf(ticket)
  const rank = stageRank(ticket, stage)
  const stepRank = stageRank(ticket, step)
  return {
    done: stepRank < rank || stage === 'delivered',
    active: stepRank === rank && stage !== 'rework',
    failed: stage === 'rework' && step === 'production',
  }
}

function latestRun(ticket: CustomDeliveryTicket): CustomDeliveryRun | undefined {
  const runs = ticket.custom_delivery?.runs || []
  return runs[runs.length - 1]
}

function runCount(ticket: CustomDeliveryTicket): number {
  return ticket.custom_delivery?.runs?.length || 0
}

function runStatusLabel(status?: string): string {
  return ({ done: '完成', running: '运行中', queued: '排队中', error: '失败' } as Record<string, string>)[String(status || '')] || String(status || '未知')
}

function gateClass(ticket: CustomDeliveryTicket): string {
  if (ticket.custom_delivery?.gate_ok) return 'is-pass'
  if (stageOf(ticket) === 'rework') return 'is-fail'
  return 'is-wait'
}

function gateIcon(ticket: CustomDeliveryTicket): string {
  if (ticket.custom_delivery?.gate_ok) return 'fa-check-circle'
  if (stageOf(ticket) === 'rework') return 'fa-times-circle'
  return 'fa-clock-o'
}

function gateTitle(ticket: CustomDeliveryTicket): string {
  if (ticket.custom_delivery?.gate_ok) return '生产质量门已通过'
  if (stageOf(ticket) === 'rework') return '生产质量门未通过'
  return '等待质量门结果'
}

function artifactCount(ticket: CustomDeliveryTicket): number {
  return ticket.custom_delivery?.artifacts?.length || 0
}

function installedArtifactCount(ticket: CustomDeliveryTicket): number {
  return ticket.custom_delivery?.install_receipts?.length || 0
}

function receiptFor(ticket: CustomDeliveryTicket, kind: string, id: string) {
  return (ticket.custom_delivery?.install_receipts || []).find((row) => row.kind === kind && row.id === id)
}

function canAccept(ticket: CustomDeliveryTicket): boolean {
  const acceptance = String(ticket.custom_delivery?.acceptance_status || 'pending')
  return stageOf(ticket) === 'acceptance'
    && ticket.custom_delivery?.gate_ok === true
    && acceptance === 'pending'
}

async function acceptDelivery(ticket: CustomDeliveryTicket) {
  if (!canAccept(ticket)) return
  const confirmed = await appConfirm(
    `确认 ${ticket.ticket_no || ticket.title || ticket.id} 已通过内部质量检查？\n\n本操作不会代替客户“${customerName(ticket)}”验收，客户仍须本人确认并安装。`,
    { title: '内部质量确认', confirmText: '确认质量通过' },
  )
  if (!confirmed) return
  busyTicketId.value = ticket.id
  try {
    await xcmaxAdminApi.decideCustomDelivery(ticket.id, 'accept', '管理员仅完成内部质量确认，等待客户本人验收')
    await loadAll()
  } catch (error) {
    await appAlert(`验收失败：${error instanceof Error ? error.message : String(error)}`)
  } finally {
    busyTicketId.value = null
  }
}

async function requestRework(ticket: CustomDeliveryTicket) {
  const note = String(reworkNotes[ticket.id] || '').trim()
  if (note.length < 4) {
    await appAlert('请填写至少 4 个字的具体返工原因')
    return
  }
  const confirmed = await appConfirm(
    `将工单 ${ticket.ticket_no || ticket.id} 发回 AI 生产员工重新执行？\n\n返工原因：${note}`,
    { title: '发起返工', confirmText: '确认返工' },
  )
  if (!confirmed) return
  busyTicketId.value = ticket.id
  try {
    await xcmaxAdminApi.decideCustomDelivery(ticket.id, 'rework', note)
    reworkNotes[ticket.id] = ''
    await loadAll()
  } catch (error) {
    await appAlert(`返工失败：${error instanceof Error ? error.message : String(error)}`)
  } finally {
    busyTicketId.value = null
  }
}

onMounted(loadAll)
</script>

<style scoped src="./DeliveryCenterView.css"></style>
