<template>
  <div class="delivery-center page-content" id="view-delivery-center">
    <header class="delivery-hero">
      <div>
        <p class="delivery-eyebrow">CUSTOMER DELIVERY CONTROL</p>
        <h2>客户交付中心</h2>
        <p>从需求、AI 生产、质量门、客户验收到安装回执，统一查看真实交付状态。</p>
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

    <section class="delivery-toolbar" aria-label="交付筛选">
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
      <span>显示 {{ filteredTickets.length }} / {{ tickets.length }} 项</span>
    </section>

    <div v-if="errorMessage" class="delivery-alert" role="alert">
      <i class="fa fa-exclamation-circle" aria-hidden="true"></i>
      <div>
        <strong>交付数据暂时无法读取</strong>
        <p>{{ errorMessage }}</p>
      </div>
      <button type="button" @click="loadAll">重试</button>
    </div>

    <div v-else-if="loading && !tickets.length" class="delivery-empty">
      <i class="fa fa-circle-o-notch fa-spin" aria-hidden="true"></i>
      <strong>正在汇总客户交付证据</strong>
      <span>会同时读取客户身份、生产运行、质量门和安装回执。</span>
    </div>

    <div v-else-if="!filteredTickets.length" class="delivery-empty">
      <i class="fa fa-inbox" aria-hidden="true"></i>
      <strong>{{ tickets.length ? '没有符合筛选条件的交付' : '暂无客户定制交付' }}</strong>
      <span>客户从企业端提交定制模块或 AI 员工需求后，会进入这里。</span>
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
            v-for="step in timelineSteps"
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

        <footer class="delivery-actions">
          <div class="delivery-actions__note">
            <i class="fa fa-shield" aria-hidden="true"></i>
            <span>管理员操作会写入客服审计记录；不把“已生成”冒充“已安装”。</span>
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
              管理员代验收
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
import { computed, onMounted, reactive, ref } from 'vue'
import {
  xcmaxAdminApi,
  type CustomDeliveryArtifact,
  type CustomDeliveryRun,
  type CustomDeliveryTicket,
  type MarketAdminUser,
} from '@/api/xcmaxAdmin'
import { appAlert, appConfirm } from '@/utils/appDialog'

const tickets = ref<CustomDeliveryTicket[]>([])
const usersById = ref(new Map<number, MarketAdminUser>())
const query = ref('')
const stageFilter = ref('')
const loading = ref(false)
const errorMessage = ref('')
const busyTicketId = ref<number | null>(null)
const reworkNotes = reactive<Record<number, string>>({})

const stageOptions = [
  { value: 'queued', label: '已受理' },
  { value: 'production', label: 'AI 生产中' },
  { value: 'acceptance', label: '待验收' },
  { value: 'rework', label: '待返工' },
  { value: 'delivering', label: '待安装回执' },
  { value: 'delivered', label: '已交付' },
]

const timelineSteps = [
  { key: 'queued', label: '需求受理', hint: '客户资料入单', icon: 'fa-file-text-o' },
  { key: 'production', label: 'AI 生产', hint: '真实运行与产物', icon: 'fa-cogs' },
  { key: 'acceptance', label: '质量验收', hint: '质量门与确认', icon: 'fa-check-square-o' },
  { key: 'delivering', label: '客户安装', hint: '下载并安装', icon: 'fa-download' },
  { key: 'delivered', label: '回执闭环', hint: '安装证据齐全', icon: 'fa-flag-checkered' },
]

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
    { key: 'all', label: '全部交付', value: tickets.value.length, hint: '真实客户定制工单' },
    { key: 'production', label: '生产进行中', value: count(['queued', 'production']), hint: '等待产物与质量证据' },
    { key: 'risk', label: '需要处理', value: count(['rework', 'acceptance']), hint: '返工或管理员验收' },
    { key: 'receipt', label: '等待回执', value: count(['delivering']), hint: '客户尚未完成安装' },
    { key: 'done', label: '闭环完成', value: count(['delivered']), hint: '安装回执已经齐全' },
  ]
})

function extractUsers(raw: unknown): MarketAdminUser[] {
  const body = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const nested = body.data && typeof body.data === 'object' ? body.data as Record<string, unknown> : {}
  const rows = Array.isArray(body.users) ? body.users : Array.isArray(nested.users) ? nested.users : []
  return rows as MarketAdminUser[]
}

function extractTickets(raw: unknown): CustomDeliveryTicket[] {
  const body = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const nested = body.data && typeof body.data === 'object' ? body.data as Record<string, unknown> : {}
  const rows = Array.isArray(body.items) ? body.items : Array.isArray(nested.items) ? nested.items : []
  return rows as CustomDeliveryTicket[]
}

async function loadAll() {
  loading.value = true
  errorMessage.value = ''
  try {
    const [deliveryResult, userResult] = await Promise.all([
      xcmaxAdminApi.listCustomDeliveries(100),
      xcmaxAdminApi.listUsers(),
    ])
    tickets.value = extractTickets(deliveryResult)
    usersById.value = new Map(extractUsers(userResult).map((user) => [user.id, user]))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
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

function stageRank(stage: string): number {
  return ({ queued: 0, production: 1, rework: 1, acceptance: 2, delivering: 3, delivered: 4 } as Record<string, number>)[stage] ?? 0
}

function timelineClass(ticket: CustomDeliveryTicket, step: string): Record<string, boolean> {
  const stage = stageOf(ticket)
  const rank = stageRank(stage)
  const stepRank = stageRank(step)
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
  return stageOf(ticket) === 'acceptance' && ticket.custom_delivery?.gate_ok === true
}

async function acceptDelivery(ticket: CustomDeliveryTicket) {
  if (!canAccept(ticket)) return
  const confirmed = await appConfirm(
    `确认代表客户“${customerName(ticket)}”验收 ${ticket.ticket_no || ticket.title || ticket.id}？\n\n此操作会写入审计记录，之后客户仍需安装并回传回执。`,
    { title: '管理员代客户验收', confirmText: '确认验收' },
  )
  if (!confirmed) return
  busyTicketId.value = ticket.id
  try {
    await xcmaxAdminApi.decideCustomDelivery(ticket.id, 'accept', '管理员在客户交付中心代为验收')
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

<style scoped>
.delivery-center {
  --ink: #132a46;
  --muted: #6e8097;
  --line: #d9e5f2;
  --blue: #2576d9;
  min-height: 100%;
  color: var(--ink);
  background:
    radial-gradient(circle at 95% 0%, rgba(60, 137, 226, 0.14), transparent 30%),
    linear-gradient(180deg, #f4f8fd 0%, #edf4fb 100%);
  padding: 24px 28px 42px;
  overflow: auto;
}

.delivery-hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 20px; }
.delivery-eyebrow { margin: 0 0 7px; color: #3d78bc; font-size: 10px; font-weight: 800; letter-spacing: .18em; }
.delivery-hero h2 { margin: 0; font-size: 28px; letter-spacing: -.02em; }
.delivery-hero p:not(.delivery-eyebrow) { margin: 8px 0 0; color: var(--muted); font-size: 13px; }
.delivery-refresh { border: 1px solid #bcd2eb; border-radius: 11px; background: rgba(255,255,255,.88); color: #1f5f9f; padding: 10px 14px; font-weight: 700; cursor: pointer; box-shadow: 0 8px 25px rgba(25,70,115,.08); }
.delivery-refresh:disabled { opacity: .55; cursor: wait; }

.delivery-stats { display: grid; grid-template-columns: repeat(5, minmax(130px,1fr)); gap: 11px; margin-bottom: 16px; }
.delivery-stats article { position: relative; overflow: hidden; min-height: 92px; padding: 14px 16px; border: 1px solid rgba(196,214,233,.9); border-radius: 14px; background: rgba(255,255,255,.9); box-shadow: 0 8px 25px rgba(26,62,100,.055); }
.delivery-stats article::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 3px; background: #84a9d0; }
.delivery-stats .is-production::before { background: #2f7ed7; }
.delivery-stats .is-risk::before { background: #e7903f; }
.delivery-stats .is-receipt::before { background: #8b69c8; }
.delivery-stats .is-done::before { background: #3b9b78; }
.delivery-stats span,.delivery-stats small { display: block; color: var(--muted); font-size: 11px; }
.delivery-stats strong { display: block; margin: 4px 0 1px; font-size: 25px; }

.delivery-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; padding: 10px; border: 1px solid var(--line); border-radius: 13px; background: rgba(255,255,255,.78); }
.delivery-toolbar label { display: flex; align-items: center; gap: 9px; flex: 1; min-width: 220px; padding: 0 10px; color: #7690ac; }
.delivery-toolbar input { width: 100%; border: 0; outline: 0; background: transparent; color: var(--ink); font-size: 13px; }
.delivery-toolbar select { border: 1px solid #cbdbea; border-radius: 9px; background: #fff; padding: 8px 10px; color: #34516f; }
.delivery-toolbar > span { color: var(--muted); font-size: 12px; white-space: nowrap; }

.delivery-alert,.delivery-empty { display: flex; align-items: center; justify-content: center; gap: 14px; min-height: 200px; border: 1px dashed #bfd2e6; border-radius: 16px; background: rgba(255,255,255,.7); color: var(--muted); }
.delivery-alert { justify-content: flex-start; min-height: auto; padding: 15px; border-style: solid; border-color: #f0c7c7; color: #9e3f3f; }
.delivery-alert i,.delivery-empty i { font-size: 24px; }
.delivery-alert strong,.delivery-empty strong,.delivery-empty span { display: block; }
.delivery-alert p { margin: 4px 0 0; }
.delivery-alert button { margin-left: auto; border: 0; border-radius: 8px; background: #a94848; color: #fff; padding: 8px 13px; }
.delivery-empty { flex-direction: column; text-align: center; }
.delivery-empty strong { color: #385673; font-size: 15px; }
.delivery-empty span { font-size: 12px; }

.delivery-list { display: grid; gap: 16px; }
.delivery-ticket { overflow: hidden; border: 1px solid #cfdeed; border-radius: 17px; background: rgba(255,255,255,.94); box-shadow: 0 12px 32px rgba(24,58,94,.07); }
.delivery-ticket__head { display: flex; justify-content: space-between; gap: 16px; padding: 17px 18px 14px; border-bottom: 1px solid #e2ebf4; }
.delivery-customer { display: flex; align-items: center; gap: 12px; min-width: 0; }
.delivery-customer__avatar { display: grid; place-items: center; width: 38px; height: 38px; flex: 0 0 38px; border-radius: 12px; background: linear-gradient(135deg,#2e7bd5,#63a2e5); color: white; font-weight: 800; box-shadow: 0 7px 15px rgba(38,112,195,.2); }
.delivery-customer__line { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.delivery-customer__line > span:not(.stage-tag) { border-radius: 999px; background: #edf4fb; color: #527291; padding: 3px 7px; font-size: 10px; }
.delivery-customer p { margin: 4px 0 0; color: #48627e; font-size: 13px; }
.stage-tag { border-radius: 999px; padding: 3px 8px; font-size: 10px; font-weight: 700; background: #e7f1fd; color: #276bb7; }
.stage-tag.is-rework { background: #fff0e6; color: #b46325; }
.stage-tag.is-delivered { background: #e4f6ee; color: #247b5c; }
.stage-tag.is-delivering { background: #efeafa; color: #6c50a7; }
.delivery-ticket__meta { display: grid; align-content: center; justify-items: end; gap: 3px; color: var(--muted); font-size: 11px; white-space: nowrap; }
.delivery-ticket__meta span { color: #355878; font-family: ui-monospace,SFMono-Regular,Menlo,monospace; }

.delivery-timeline { display: grid; grid-template-columns: repeat(5,1fr); margin: 0; padding: 16px 20px; list-style: none; background: linear-gradient(90deg,#f9fbfe,#f3f8fd); }
.delivery-timeline li { position: relative; display: flex; align-items: center; gap: 8px; color: #8798aa; }
.delivery-timeline li:not(:last-child)::after { content: ''; position: absolute; top: 14px; left: 32px; right: 6px; height: 1px; background: #cfdeeb; }
.delivery-timeline li > span { z-index: 1; display: grid; place-items: center; width: 28px; height: 28px; flex: 0 0 28px; border-radius: 50%; background: #fff; border: 1px solid #ccdae8; }
.delivery-timeline strong,.delivery-timeline small { display: block; }
.delivery-timeline strong { color: #597087; font-size: 11px; }
.delivery-timeline small { font-size: 9px; }
.delivery-timeline .done > span,.delivery-timeline .active > span { border-color: #4b91dc; background: #2f7ed7; color: #fff; }
.delivery-timeline .done:not(:last-child)::after { background: #6fa5dc; }
.delivery-timeline .active strong { color: #2469af; }
.delivery-timeline .failed > span { border-color: #e79d61; background: #ed8b3b; color: #fff; }
.delivery-timeline .failed strong { color: #b26225; }

.delivery-ticket__body { display: grid; grid-template-columns: minmax(0,1.5fr) minmax(260px,.75fr); gap: 16px; padding: 16px 18px; }
.delivery-brief { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.delivery-brief > div { padding: 13px; border: 1px solid #e0e9f2; border-radius: 12px; background: #fbfdff; }
.delivery-brief h3,.delivery-artifacts h3 { margin: 0 0 7px; color: #3a5876; font-size: 11px; letter-spacing: .05em; }
.delivery-brief p { margin: 0; color: #4d6075; font-size: 12px; line-height: 1.65; white-space: pre-wrap; }
.delivery-proof { display: grid; gap: 10px; }
.delivery-gate { display: flex; align-items: center; gap: 10px; padding: 12px; border: 1px solid #d9e5ef; border-radius: 12px; background: #f7fafc; }
.delivery-gate > i { font-size: 22px; }
.delivery-gate strong,.delivery-gate span { display: block; }
.delivery-gate strong { font-size: 12px; }
.delivery-gate span { margin-top: 3px; color: var(--muted); font-size: 10px; line-height: 1.45; }
.delivery-gate.is-pass { border-color: #bfe3d4; background: #f0faf6; color: #28795c; }
.delivery-gate.is-fail { border-color: #efc9b3; background: #fff7f1; color: #b26225; }
.delivery-gate.is-wait { color: #527291; }
.delivery-run { display: grid; grid-template-columns: repeat(3,1fr); gap: 7px; }
.delivery-run > div { padding: 8px; border-radius: 9px; background: #f1f6fb; }
.delivery-run span,.delivery-run strong { display: block; }
.delivery-run span { color: var(--muted); font-size: 9px; }
.delivery-run strong { margin-top: 2px; color: #355573; font-size: 11px; }
.delivery-run__error { grid-column: 1/-1; margin: 0; padding: 8px; border-radius: 8px; background: #fff0f0; color: #a94343; font-size: 10px; white-space: pre-wrap; }

.delivery-artifacts { margin: 0 18px 15px; padding: 13px; border: 1px solid #e0e9f2; border-radius: 12px; background: #f9fbfd; }
.delivery-artifacts > header { display: flex; align-items: center; justify-content: space-between; }
.delivery-artifacts > header span { color: var(--muted); font-size: 10px; }
.delivery-artifact-list { display: grid; gap: 7px; }
.delivery-artifact-list > div { display: flex; align-items: center; gap: 9px; padding: 8px 10px; border-radius: 9px; background: #fff; }
.delivery-artifact-list i { width: 18px; color: #3979bd; text-align: center; }
.delivery-artifact-list strong,.delivery-artifact-list code { display: block; }
.delivery-artifact-list strong { font-size: 10px; }
.delivery-artifact-list code { margin-top: 2px; color: #5f7185; font-size: 10px; }
.receipt { margin-left: auto; border-radius: 999px; background: #f2f4f7; color: #7b8794; padding: 4px 8px; font-size: 9px; }
.receipt.is-installed { background: #e7f6ef; color: #28795c; }
.delivery-artifacts__empty { margin: 0; color: #8997a6; font-size: 11px; }

.delivery-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 18px; border-top: 1px solid #e1eaf3; background: #fbfdff; }
.delivery-actions__note { display: flex; align-items: center; gap: 7px; color: #75879a; font-size: 10px; }
.delivery-actions__note i { color: #4b83bd; }
.delivery-actions__controls { display: flex; gap: 7px; flex: 1; justify-content: flex-end; }
.delivery-actions__controls input { width: min(330px,38vw); border: 1px solid #cfdeec; border-radius: 8px; padding: 7px 9px; font-size: 11px; outline: 0; }
.delivery-actions__controls input:focus { border-color: #6099d5; box-shadow: 0 0 0 3px rgba(61,130,204,.1); }
.action-primary,.action-secondary { border-radius: 8px; padding: 7px 11px; font-size: 10px; font-weight: 700; cursor: pointer; }
.action-primary { border: 1px solid #2873c7; background: #2878d0; color: #fff; }
.action-secondary { border: 1px solid #d6a37c; background: #fff7f1; color: #a95c24; }
.action-primary:disabled,.action-secondary:disabled { opacity: .5; cursor: wait; }
.delivery-complete { color: #2a8161; font-size: 11px; }

@media (max-width: 1100px) {
  .delivery-stats { grid-template-columns: repeat(3,1fr); }
  .delivery-ticket__body { grid-template-columns: 1fr; }
  .delivery-actions { align-items: flex-start; flex-direction: column; }
  .delivery-actions__controls { width: 100%; }
  .delivery-actions__controls input { width: 100%; }
}

@media (max-width: 760px) {
  .delivery-center { padding: 18px 14px 32px; }
  .delivery-hero,.delivery-ticket__head { flex-direction: column; }
  .delivery-stats { grid-template-columns: repeat(2,1fr); }
  .delivery-toolbar { align-items: stretch; flex-direction: column; }
  .delivery-timeline { overflow-x: auto; grid-template-columns: repeat(5,150px); }
  .delivery-brief { grid-template-columns: 1fr; }
  .delivery-ticket__meta { justify-items: start; }
  .delivery-actions__controls { flex-wrap: wrap; }
}
</style>
