<template>
  <div class="employee-inbox" id="view-employee-inbox">
    <header class="inbox-header">
      <div>
        <p class="eyebrow">XCMAX · 管理端真实员工</p>
        <h1>员工待办与交付</h1>
        <p class="subtitle">任务不会因为聊天结束而消失；员工必须持续汇报、提交证据并等待验收。</p>
      </div>
      <button class="button secondary" :disabled="loading" type="button" @click="refresh(true)">
        <i class="fa fa-refresh" :class="{ 'fa-spin': loading }" aria-hidden="true"></i>
        刷新
      </button>
    </header>

    <section class="summary-grid" aria-label="员工任务概况">
      <article class="summary-card">
        <span>正在推进</span><strong>{{ summary.active || 0 }}</strong>
      </article>
      <article class="summary-card is-decision">
        <span>等你决策</span><strong>{{ summary.pending_decisions || 0 }}</strong>
      </article>
      <article class="summary-card is-delivery">
        <span>等待验收</span><strong>{{ summary.by_status?.delivered || 0 }}</strong>
      </article>
      <article class="summary-card is-blocked">
        <span>需要介入</span><strong>{{ summary.blocked || 0 }}</strong>
      </article>
    </section>

    <section class="create-card">
      <div class="section-title">
        <div><span class="step">01</span><h2>安排一项真实工作</h2></div>
        <span class="contract">创建后立即获得持久 task_id</span>
      </div>
      <div class="create-grid">
        <label>
          <span>任务标题</span>
          <input v-model="form.title" placeholder="例如：修复管理端消息推送并完成验收" />
        </label>
        <label>
          <span>责任员工（仅管理端在岗员工）</span>
          <select v-model="form.owner">
            <option value="auto">智能自动选人（推荐）</option>
            <option v-for="employee in managementEmployees" :key="employee.employee_id" :value="employee.employee_id" :disabled="!employee.primary_assignable">
              {{ employee.name }} · {{ employee.area }}{{ employee.primary_assignable ? '' : ' · 当前不可派发' }}
            </option>
          </select>
        </label>
        <label class="span-two">
          <span>具体要求</span>
          <textarea v-model="form.description" rows="3" placeholder="说明目标、边界和需要交付的结果"></textarea>
        </label>
        <label>
          <span>优先级</span>
          <select v-model="form.priority"><option>P0</option><option>P1</option><option>P2</option><option>P3</option></select>
        </label>
        <label>
          <span>验收标准</span>
          <input v-model="form.acceptance" placeholder="例如：桌面和手机均收到一次通知" />
        </label>
      </div>
      <div class="create-actions">
        <span v-if="createError" class="error-text">{{ createError }}</span>
        <button class="button primary" type="button" :disabled="creating || !canCreate" @click="createTask">
          {{ creating ? '正在建任务…' : '交给员工执行' }}
        </button>
      </div>
    </section>

    <section class="work-board">
      <div class="board-toolbar">
        <div class="section-title compact"><div><span class="step">02</span><h2>持续执行与验收</h2></div></div>
        <div class="filters" role="tablist">
          <button v-for="filter in filters" :key="filter.value" type="button" :class="{ active: activeFilter === filter.value }" @click="activeFilter = filter.value">
            {{ filter.label }}
          </button>
        </div>
      </div>

      <p v-if="loadError" class="load-error">{{ loadError }}</p>
      <div v-if="filteredItems.length" class="task-list">
        <article v-for="item in filteredItems" :key="item.task_id" class="task-card" :class="`status-${item.status}`">
          <button class="task-main" type="button" @click="toggleDetail(item)">
            <span class="priority">{{ item.priority }}</span>
            <span class="task-copy">
              <strong>{{ item.title }}</strong>
              <small>{{ item.owner_employee_id }} · {{ statusLabel(item.status) }}</small>
            </span>
            <span class="task-progress"><b>{{ item.progress || 0 }}%</b><i><em :style="{ width: `${item.progress || 0}%` }"></em></i></span>
            <span class="updated">{{ relativeTime(item.updated_at) }}</span>
          </button>

          <div v-if="selectedTaskId === item.task_id" class="task-detail">
            <div class="detail-grid">
              <div><span>当前阶段</span><strong>{{ selectedDetail?.current_stage || '等待员工领取' }}</strong></div>
              <div><span>执行次数</span><strong>{{ selectedDetail?.attempt_count || 0 }} / {{ selectedDetail?.max_attempts || 0 }}</strong></div>
              <div><span>最近心跳</span><strong>{{ formatTime(selectedDetail?.heartbeat_at) }}</strong></div>
              <div><span>任务编号</span><strong class="mono">{{ item.task_id }}</strong></div>
            </div>
            <p v-if="selectedDetail?.last_update" class="employee-update">{{ selectedDetail.last_update }}</p>
            <p v-if="selectedDetail?.error" class="task-error">{{ selectedDetail.error }}</p>

            <div v-if="pendingDecision" class="decision-box">
              <span class="decision-kicker">员工正在等你</span>
              <h3>{{ pendingDecision.question }}</h3>
              <p v-if="pendingDecision.recommendation">员工建议：{{ pendingDecision.recommendation }}</p>
              <div class="decision-options">
                <button v-for="option in pendingDecision.options" :key="String(option)" type="button" class="button primary" :disabled="acting" @click="answerDecision(String(option))">{{ option }}</button>
              </div>
              <div class="inline-answer">
                <input v-model="decisionAnswer" placeholder="也可以输入你的决定" />
                <button class="button secondary" type="button" :disabled="acting || !decisionAnswer.trim()" @click="answerDecision(decisionAnswer)">回复员工</button>
              </div>
            </div>

            <section v-if="hasAuditTrail || item.status === 'delivered'" class="audit-board" aria-label="独立证据与恢复审计">
              <div class="audit-board-title">
                <div>
                  <span class="decision-kicker">独立审计账</span>
                  <h3>事实证据、验收回执与副作用恢复</h3>
                </div>
                <span class="attempt-chip">当前第 {{ selectedDetail?.attempt_count || 0 }} 次执行</span>
              </div>

              <div class="audit-grid">
                <section class="audit-section">
                  <header><strong>事实证据</strong><span>{{ factEvidence.length }} 项</span></header>
                  <ul v-if="factEvidence.length" class="audit-list">
                    <li v-for="fact in factEvidence" :key="fact.evidence_id" class="audit-item" :class="{ historical: fact.attempt !== selectedDetail?.attempt_count }">
                      <div class="audit-item-head">
                        <div>
                          <span class="status-pill" :class="statusClass(fact.status)">{{ factStatusLabel(fact.status) }}</span>
                          <strong>{{ factKindLabel(fact.kind) }}</strong>
                        </div>
                        <small>第 {{ fact.attempt }} 次</small>
                      </div>
                      <dl>
                        <div><dt>来源</dt><dd :title="factSource(fact)">{{ factSource(fact) }}</dd></div>
                        <div><dt>观测时间</dt><dd>{{ formatTime(fact.observed_at) }}</dd></div>
                        <div><dt>观测哈希</dt><dd class="mono" :title="factObservedHash(fact)">{{ shortHash(factObservedHash(fact)) }}</dd></div>
                        <div><dt>封存哈希</dt><dd class="mono" :title="fact.payload_sha256 || ''">{{ shortHash(fact.payload_sha256) }}</dd></div>
                      </dl>
                      <div v-if="factChecks(fact).length" class="check-list">
                        <span v-for="check in factChecks(fact)" :key="check.name" :class="check.passed ? 'check-pass' : 'check-fail'">
                          {{ checkLabel(check.name) }} · {{ check.passed ? '通过' : '失败' }}
                        </span>
                      </div>
                      <p v-if="factError(fact)" class="audit-error">{{ factError(fact) }}</p>
                    </li>
                  </ul>
                  <p v-else class="audit-empty">当前还没有独立事实采集结果。</p>
                </section>

                <section class="audit-section">
                  <header><strong>验收回执</strong><span>{{ verificationReceipts.length }} 张</span></header>
                  <ul v-if="verificationReceipts.length" class="audit-list">
                    <li v-for="receipt in verificationReceipts" :key="receipt.receipt_id" class="audit-item receipt-item" :class="{ historical: receipt.attempt !== selectedDetail?.attempt_count }">
                      <div class="audit-item-head">
                        <div>
                          <span class="status-pill" :class="statusClass(receipt.status)">{{ receiptStatusLabel(receipt.status) }}</span>
                          <strong>第 {{ receipt.attempt }} 次独立签收</strong>
                        </div>
                        <small v-if="receipt.attempt === selectedDetail?.attempt_count">当前</small>
                      </div>
                      <div class="outcome-row">
                        <span :class="statusClass(receipt.fact_outcome)">事实 {{ outcomeLabel(receipt.fact_outcome) }}</span>
                        <span :class="statusClass(receipt.audit_outcome)">语义 {{ outcomeLabel(receipt.audit_outcome) }}</span>
                      </div>
                      <dl>
                        <div><dt>签收员</dt><dd>{{ receipt.verifier_employee_id || 'delivery-receipt-officer' }}</dd></div>
                        <div><dt>生成时间</dt><dd>{{ formatTime(receipt.created_at) }}</dd></div>
                        <div><dt>结果哈希</dt><dd class="mono" :title="receipt.result_digest">{{ shortHash(receipt.result_digest) }}</dd></div>
                        <div><dt>事实包哈希</dt><dd class="mono" :title="receipt.fact_bundle_digest">{{ shortHash(receipt.fact_bundle_digest) }}</dd></div>
                      </dl>
                      <p v-if="receiptReason(receipt)" class="audit-note">{{ receiptReason(receipt) }}</p>
                    </li>
                  </ul>
                  <p v-else class="audit-empty">还没有独立验收回执。</p>
                </section>

                <section class="audit-section operations-section">
                  <header><strong>外部操作与补偿</strong><span>{{ operations.length }} 项</span></header>
                  <ul v-if="operations.length" class="audit-list">
                    <li v-for="operation in operations" :key="operation.operation_id" class="audit-item operation-item" :class="{ historical: operation.attempt !== selectedDetail?.attempt_count }">
                      <div class="audit-item-head">
                        <div>
                          <span class="status-pill" :class="statusClass(operation.status)">{{ operationStatusLabel(operation.status) }}</span>
                          <strong>{{ operation.logical_step || operation.kind }}</strong>
                        </div>
                        <small>第 {{ operation.attempt }} 次</small>
                      </div>
                      <dl>
                        <div><dt>类型</dt><dd>{{ operation.kind || 'unknown' }}</dd></div>
                        <div><dt>目标</dt><dd :title="operation.target">{{ operation.target || '—' }}</dd></div>
                        <div><dt>请求哈希</dt><dd class="mono" :title="operation.request_digest">{{ shortHash(operation.request_digest) }}</dd></div>
                        <div><dt>外部回执</dt><dd :title="operation.external_ref || ''">{{ operation.external_ref || '—' }}</dd></div>
                      </dl>
                      <div class="compensation-row">
                        <span :class="compensationClass(operation.compensation_status)">{{ compensationStatusLabel(operation.compensation_status) }}</span>
                        <small>{{ operation.reversible ? '可逆操作' : '不可逆或无需回滚' }}</small>
                      </div>
                      <p v-if="operation.error" class="audit-error">{{ operation.error }}</p>
                    </li>
                  </ul>
                  <p v-else class="audit-empty">本任务没有登记外部副作用操作。</p>
                </section>
              </div>
            </section>

            <div v-if="item.status === 'delivered'" class="delivery-box">
              <span class="decision-kicker">员工已交付，尚未算完成</span>
              <h3>{{ selectedDetail?.result_summary || '已提交执行结果' }}</h3>
              <p>证据 {{ selectedDetail?.evidence?.length || 0 }} 项 · 产物 {{ selectedDetail?.artifacts?.length || 0 }} 项</p>
              <div class="verification-gate" :class="canAcceptDelivery ? 'gate-pass' : 'gate-blocked'">
                <i class="fa" :class="canAcceptDelivery ? 'fa-check-circle' : 'fa-lock'" aria-hidden="true"></i>
                <div>
                  <strong>{{ canAcceptDelivery ? '当前交付满足安全验收门禁' : '当前交付仍有验收阻断项' }}</strong>
                  <span v-if="currentPassReceipt">{{ currentPassReceipt.receipt_id }} · {{ formatTime(currentPassReceipt.created_at) }}</span>
                  <span v-else-if="currentReceipt">回执 {{ outcomeLabel(currentReceipt.status) }} · 事实 {{ outcomeLabel(currentReceipt.fact_outcome) }} · 语义 {{ outcomeLabel(currentReceipt.audit_outcome) }}</span>
                  <span v-else>必须完成独立事实采集、语义验收和副作用收口后，才能由老板接受。</span>
                  <ul v-if="acceptanceBlockers.length" class="gate-blockers">
                    <li v-for="blocker in acceptanceBlockers" :key="blocker">{{ blocker }}</li>
                  </ul>
                </div>
              </div>
              <textarea v-model="reviewFeedback" rows="2" placeholder="验收意见或返工要求"></textarea>
              <span v-if="reviewError" class="error-text">{{ reviewError }}</span>
              <div class="decision-options">
                <button class="button success" type="button" :disabled="acting || !canAcceptDelivery" :title="canAcceptDelivery ? '接受当前交付' : (acceptanceBlockers[0] || '当前交付不满足安全验收门禁')" @click="review(true)">验收通过</button>
                <button class="button danger" type="button" :disabled="acting" @click="review(false)">退回返工</button>
              </div>
            </div>

            <div v-if="item.status === 'blocked' || item.status === 'failed'" class="blocked-box">
              <span>员工已停止，不会假装完成。</span>
              <button class="button danger" type="button" :disabled="acting" @click="retryTask">修复后重新派发</button>
            </div>

            <div v-if="item.status === 'cancel_requested'" class="stopping-box">
              <strong>正在安全停止</strong>
              <span>台账已禁止后续验收和交付；已启动的当前步骤返回后收口。</span>
            </div>

            <div v-if="canCancel(item) || canReassign(item)" class="control-box">
              <div>
                <span class="decision-kicker">老板控制</span>
                <p>改派只能选管理编制员工；运行中需先安全停止。</p>
              </div>
              <input v-model="controlReason" placeholder="停止或改派原因（会写入审计时间线）" />
              <div class="control-actions">
                <select v-if="canReassign(item)" v-model="reassignEmployee">
                  <option value="">选择新负责人</option>
                  <option v-for="employee in managementEmployees" :key="employee.employee_id" :value="employee.employee_id" :disabled="!employee.primary_assignable || employee.employee_id === item.owner_employee_id">
                    {{ employee.name }} · {{ employee.employee_id }}
                  </option>
                </select>
                <button v-if="canReassign(item)" class="button secondary" type="button" :disabled="acting || !reassignEmployee" @click="reassignTask">改派员工</button>
                <button v-if="canCancel(item)" class="button danger" type="button" :disabled="acting" @click="cancelTask(item)">请求停止</button>
              </div>
              <span v-if="actionError" class="error-text">{{ actionError }}</span>
            </div>

            <ol v-if="selectedDetail?.events?.length" class="timeline">
              <li v-for="event in selectedDetail.events" :key="event.id">
                <i></i><div><strong>{{ eventLabel(event.event_type) }}</strong><span>{{ event.message || formatTime(event.created_at) }}</span></div>
              </li>
            </ol>
          </div>
        </article>
      </div>
      <div v-else class="empty-state">
        <i class="fa fa-check-circle-o" aria-hidden="true"></i>
        <strong>当前筛选下没有任务</strong>
        <span>上面安排的工作会在这里持续显示，刷新或重启桌面也不会丢失。</span>
      </div>
    </section>
  </div>
</template>

<script lang="ts">
export default { name: 'AdminEmployeeInboxView' }
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  managementAcceptanceGate,
  managementWorkApi,
  type ManagementDecision,
  type ManagementDutyEmployee,
  type ManagementFactEvidence,
  type ManagementVerificationReceipt,
  type ManagementWorkItem,
  type ManagementWorkOperation,
  type ManagementWorkSummary,
} from '@/api/managementWork'

const managementEmployees = ref<ManagementDutyEmployee[]>([])
const filters = [
  { label: '进行中', value: 'active' },
  { label: '等我处理', value: 'attention' },
  { label: '已验收', value: 'accepted' },
  { label: '全部', value: 'all' },
]
const activeFilter = ref('active')
const items = ref<ManagementWorkItem[]>([])
const summary = ref<ManagementWorkSummary>({ by_status: {}, active: 0, pending_decisions: 0, accepted: 0, blocked: 0 })
const loading = ref(false)
const loadError = ref('')
const creating = ref(false)
const createError = ref('')
const selectedTaskId = ref('')
const selectedDetail = ref<ManagementWorkItem | null>(null)
const decisionAnswer = ref('')
const reviewFeedback = ref('')
const reviewError = ref('')
const controlReason = ref('')
const reassignEmployee = ref('')
const actionError = ref('')
const acting = ref(false)
const form = reactive({ title: '', description: '', owner: 'auto', priority: 'P1', acceptance: '' })
let refreshTimer: number | undefined

const canCreate = computed(() => Boolean(form.title.trim() && form.description.trim() && form.owner.trim()))
const filteredItems = computed(() => {
  if (activeFilter.value === 'all') return items.value
  if (activeFilter.value === 'accepted') return items.value.filter((item) => item.status === 'accepted')
  if (activeFilter.value === 'attention') return items.value.filter((item) => ['waiting_decision', 'delivered', 'blocked', 'failed'].includes(item.status))
  return items.value.filter((item) => ['assigned', 'running', 'cancel_requested', 'retrying', 'verifying', 'waiting_decision', 'delivered'].includes(item.status))
})
const pendingDecision = computed<ManagementDecision | null>(() => selectedDetail.value?.decisions?.find((decision) => decision.status === 'pending') || null)
const factEvidence = computed<ManagementFactEvidence[]>(() => selectedDetail.value?.fact_evidence || [])
const verificationReceipts = computed<ManagementVerificationReceipt[]>(() => selectedDetail.value?.verification_receipts || [])
const operations = computed<ManagementWorkOperation[]>(() => selectedDetail.value?.operations || [])
const acceptanceGate = computed(() => managementAcceptanceGate(selectedDetail.value))
const currentPassReceipt = computed<ManagementVerificationReceipt | null>(() => acceptanceGate.value.receipt)
const currentReceipt = computed<ManagementVerificationReceipt | null>(() => acceptanceGate.value.currentReceipt)
const acceptanceBlockers = computed<string[]>(() => acceptanceGate.value.blockers)
const hasAuditTrail = computed(() => Boolean(factEvidence.value.length || verificationReceipts.value.length || operations.value.length))
const canAcceptDelivery = computed(() => acceptanceGate.value.allowed)

async function refresh(showSpinner = false) {
  if (showSpinner) loading.value = true
  try {
    const result = await managementWorkApi.list({ limit: 200 })
    items.value = Array.isArray(result.items) ? result.items : []
    summary.value = result.summary || summary.value
    loadError.value = ''
    if (selectedTaskId.value) await loadDetail(selectedTaskId.value)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function loadManagementEmployees() {
  try {
    const result = await managementWorkApi.employees()
    managementEmployees.value = Array.isArray(result.employees) ? result.employees : []
  } catch {
    // 任务列表仍可使用；创建时后端会继续执行管理端编制硬校验。
  }
}

async function createTask() {
  if (!canCreate.value) return
  creating.value = true
  createError.value = ''
  try {
    const result = await managementWorkApi.create({
      title: form.title.trim(), description: form.description.trim(), owner_employee_id: form.owner.trim(),
      priority: form.priority, acceptance_required: true,
      acceptance_criteria: form.acceptance.trim() ? [form.acceptance.trim()] : [],
      idempotency_key: `desktop-${Date.now()}`,
    })
    form.title = ''; form.description = ''; form.acceptance = ''
    await refresh()
    selectedTaskId.value = result.item.task_id
    await loadDetail(result.item.task_id)
  } catch (error) {
    createError.value = error instanceof Error ? error.message : String(error)
  } finally { creating.value = false }
}

async function loadDetail(taskId: string) {
  selectedDetail.value = await managementWorkApi.detail(taskId)
}
async function toggleDetail(item: ManagementWorkItem) {
  if (selectedTaskId.value === item.task_id) { selectedTaskId.value = ''; selectedDetail.value = null; return }
  selectedTaskId.value = item.task_id; decisionAnswer.value = ''; reviewFeedback.value = ''; reviewError.value = ''; controlReason.value = ''; reassignEmployee.value = ''; actionError.value = ''; await loadDetail(item.task_id)
}
async function answerDecision(answer: string) {
  if (!pendingDecision.value || !answer.trim()) return
  acting.value = true
  try { await managementWorkApi.resolveDecision(pendingDecision.value.decision_id, answer.trim()); decisionAnswer.value = ''; await refresh() } finally { acting.value = false }
}
async function review(accepted: boolean) {
  if (!selectedTaskId.value) return
  if (accepted && !canAcceptDelivery.value) {
    reviewError.value = acceptanceBlockers.value.join('；') || '当前交付不满足安全验收门禁。'
    return
  }
  acting.value = true
  reviewError.value = ''
  try {
    await managementWorkApi.review(selectedTaskId.value, accepted, reviewFeedback.value.trim())
    reviewFeedback.value = ''
    await refresh()
  } catch (error) {
    reviewError.value = error instanceof Error ? error.message : String(error)
  } finally {
    acting.value = false
  }
}
async function retryTask() {
  if (!selectedTaskId.value) return
  acting.value = true
  try { await managementWorkApi.retry(selectedTaskId.value, '老板从员工待办重新派发'); await refresh() } finally { acting.value = false }
}

function canCancel(item: ManagementWorkItem) {
  return !['accepted', 'cancelled', 'cancel_requested'].includes(item.status)
}
function canReassign(item: ManagementWorkItem) {
  return ['assigned', 'retrying', 'waiting_decision', 'blocked', 'failed'].includes(item.status)
}
async function cancelTask(item: ManagementWorkItem) {
  if (!selectedTaskId.value) return
  const copy = item.status === 'running'
    ? '立即禁止后续验收和交付；已启动的外部动作可能需要短暂收尾。确定继续？'
    : '确定停止这项任务？状态和原因会保留在审计时间线。'
  if (!window.confirm(copy)) return
  acting.value = true
  actionError.value = ''
  try {
    await managementWorkApi.cancel(selectedTaskId.value, controlReason.value.trim())
    await refresh()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    acting.value = false
  }
}
async function reassignTask() {
  if (!selectedTaskId.value || !reassignEmployee.value) return
  acting.value = true
  actionError.value = ''
  try {
    await managementWorkApi.reassign(selectedTaskId.value, reassignEmployee.value, controlReason.value.trim())
    reassignEmployee.value = ''
    await refresh()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    acting.value = false
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}
function shortHash(value?: string | null) {
  const text = String(value || '').trim()
  if (!text) return '—'
  return text.length > 18 ? `${text.slice(0, 10)}…${text.slice(-6)}` : text
}
function factSource(fact: ManagementFactEvidence) {
  const payload = asRecord(fact.payload)
  return String(fact.source_ref || payload.source || payload.path || payload.url || payload.repo_path || '独立事实采集器')
}
function factObservedHash(fact: ManagementFactEvidence) {
  const payload = asRecord(fact.payload)
  return String(payload.sha256 || payload.body_sha256 || payload.head || payload.staged_commit_sha || '')
}
function factError(fact: ManagementFactEvidence) {
  return String(asRecord(fact.payload).error || '')
}
function factChecks(fact: ManagementFactEvidence) {
  const checks = asRecord(asRecord(fact.payload).checks)
  return Object.entries(checks).map(([name, passed]) => ({ name, passed: passed === true }))
}
function factKindLabel(kind: string) {
  return ({ file: '文件回读', git: 'Git 状态', http: 'HTTP 回读', change_request: '变更单回读' } as Record<string, string>)[kind] || kind || '未知事实'
}
function factStatusLabel(status: string) {
  return ({ pass: '已证实', fail: '未通过', unavailable: '不可用', inconclusive: '证据不足' } as Record<string, string>)[String(status || '').toLowerCase()] || status || '未知'
}
function receiptStatusLabel(status: string) {
  return String(status || '').toLowerCase() === 'pass' ? 'PASS 回执' : '未通过'
}
function outcomeLabel(status: string) {
  return ({ pass: '通过', fail: '失败', unavailable: '不可用', inconclusive: '证据不足', invalid: '无效' } as Record<string, string>)[String(status || '').toLowerCase()] || status || '未知'
}
function receiptReason(receipt: ManagementVerificationReceipt) {
  return String(asRecord(receipt.audit).reason || '')
}
function operationStatusLabel(status: string) {
  return ({ running: '执行中', succeeded: '已成功', failed: '确定失败', uncertain: '结果不确定' } as Record<string, string>)[String(status || '').toLowerCase()] || status || '未知'
}
function compensationStatusLabel(status: string) {
  return ({ available: '补偿已就绪', required: '需要补偿', compensated: '已完成补偿', conflict: '补偿冲突', failed: '补偿失败', unavailable: '无法补偿', not_required: '无需补偿' } as Record<string, string>)[String(status || '').toLowerCase()] || status || '补偿状态未知'
}
function compensationClass(status: string) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'compensated' || normalized === 'not_required') return 'compensation-ok'
  if (normalized === 'available') return 'compensation-ready'
  return 'compensation-risk'
}
function statusClass(status: string) {
  const normalized = String(status || '').toLowerCase()
  if (['pass', 'succeeded', 'compensated', 'not_required'].includes(normalized)) return 'is-pass'
  if (['running', 'available'].includes(normalized)) return 'is-running'
  if (['inconclusive', 'unavailable', 'uncertain', 'required'].includes(normalized)) return 'is-warning'
  return 'is-fail'
}
function checkLabel(name: string) {
  return ({ exists: '文件存在', sha256: '哈希一致', min_size: '文件大小', text_contains: '内容匹配', json_subset: 'JSON 匹配', head: '提交一致', changed_paths: '改动范围', clean: '工作区干净', diff_check: 'Diff 检查', repository_readable: '仓库可读', status: 'HTTP 状态', body_sha256: '响应哈希' } as Record<string, string>)[name] || name
}

function statusLabel(status: string) { return ({ assigned: '待领取', running: '执行中', cancel_requested: '正在安全停止', waiting_decision: '等你决策', retrying: '等待重试', verifying: '验证中', delivered: '等待验收', accepted: '已验收', blocked: '已阻塞', failed: '失败', cancelled: '已取消' } as Record<string, string>)[status] || status }
function eventLabel(event: string) { return ({ 'task.created': '任务创建', 'task.routed': '智能选人', 'task.claimed': '员工领取', 'task.progress': '进度汇报', 'task.verification_receipt': '独立验收回执', 'decision.requested': '请求决策', 'decision.resolved': '决策已回复', 'decision.cancelled': '决策已取消', 'decision.superseded': '原决策已作废', 'operation.started': '副作用已登记', 'operation.replayed': '副作用结果复用', 'operation.reclaimed': '副作用租约回收', 'operation.succeeded': '副作用已完成', 'operation.failed': '副作用确定失败', 'operation.uncertain': '副作用结果不确定', 'operation.compensated': '副作用已补偿', 'task.retry_scheduled': '安排重试', 'task.delivered': '提交交付', 'task.accepted': '验收通过', 'task.rejected': '退回返工', 'task.blocked': '升级人工', 'task.cancel_requested': '请求安全停止', 'task.cancelled': '任务已停止', 'task.reassigned': '任务已改派' } as Record<string, string>)[event] || event }
function formatTime(value?: string | null) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString() }
function relativeTime(value?: string | null) { if (!value) return '刚刚'; const diff = Date.now() - new Date(value).getTime(); if (diff < 60_000) return '刚刚'; if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`; if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}小时前`; return formatTime(value) }

watch(activeFilter, () => { selectedTaskId.value = ''; selectedDetail.value = null })
onMounted(() => { void loadManagementEmployees(); void refresh(true); refreshTimer = window.setInterval(() => void refresh(false), 5000) })
onBeforeUnmount(() => { if (refreshTimer) window.clearInterval(refreshTimer) })
</script>

<style scoped>
.employee-inbox { min-height: 100%; padding: 28px; color: #172033; background: radial-gradient(circle at top right, #eaf3ff 0, transparent 34%), #f4f7fb; overflow: auto; }
.inbox-header, .section-title, .board-toolbar, .create-actions, .task-main, .blocked-box { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.inbox-header h1 { margin: 4px 0 6px; font-size: 28px; letter-spacing: -.03em; }.eyebrow,.decision-kicker { margin: 0; color: #2563eb; font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }.subtitle { margin: 0; color: #64748b; font-size: 13px; }
.summary-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 12px; margin: 22px 0; }.summary-card { padding: 17px 18px; border: 1px solid #dce5f1; border-radius: 14px; background: rgba(255,255,255,.9); box-shadow: 0 8px 30px rgba(15,23,42,.04); }.summary-card span { color: #64748b; font-size: 12px; }.summary-card strong { display: block; margin-top: 6px; font-size: 27px; }.summary-card.is-decision strong { color:#d97706 }.summary-card.is-delivery strong{color:#2563eb}.summary-card.is-blocked strong{color:#dc2626}
.create-card,.work-board { margin-bottom: 18px; padding: 20px; border: 1px solid #dbe4ef; border-radius: 16px; background:#fff; box-shadow:0 12px 35px rgba(15,23,42,.05) }.section-title>div { display:flex;align-items:center;gap:10px }.section-title h2 { margin:0;font-size:17px }.section-title.compact { margin:0 }.step { display:inline-grid;place-items:center;width:27px;height:27px;border-radius:9px;background:#172033;color:#fff;font-size:10px;font-weight:800 }.contract { color:#64748b;font-size:11px }
.create-grid { display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:18px }.create-grid label span { display:block;margin-bottom:6px;color:#64748b;font-size:11px;font-weight:700 }.span-two{grid-column:1/-1} input,textarea,select { width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #cfd9e6;border-radius:9px;background:#fbfdff;color:#172033;font:inherit } textarea{resize:vertical}.create-actions{margin-top:14px}.error-text,.load-error,.task-error{color:#b91c1c;font-size:12px}
.button { border:0;border-radius:9px;padding:9px 14px;font-weight:700;cursor:pointer }.button:disabled{opacity:.5;cursor:not-allowed}.button.primary{background:#2563eb;color:#fff}.button.secondary{background:#e8eef7;color:#26354a}.button.success{background:#059669;color:#fff}.button.danger{background:#dc2626;color:#fff}
.filters{display:flex;gap:5px;padding:4px;border-radius:10px;background:#eef3f8}.filters button{border:0;padding:7px 11px;border-radius:7px;background:transparent;color:#64748b;cursor:pointer}.filters button.active{background:#fff;color:#172033;box-shadow:0 2px 8px rgba(15,23,42,.08)}.task-list{display:flex;flex-direction:column;gap:9px;margin-top:17px}.task-card{border:1px solid #dde5ef;border-left:4px solid #94a3b8;border-radius:12px;overflow:hidden}.task-card.status-running{border-left-color:#2563eb}.task-card.status-waiting_decision,.task-card.status-delivered{border-left-color:#d97706}.task-card.status-blocked,.task-card.status-failed{border-left-color:#dc2626}.task-card.status-accepted{border-left-color:#059669}.task-main{width:100%;padding:14px;border:0;background:#fff;text-align:left;cursor:pointer}.priority{padding:4px 7px;border-radius:6px;background:#172033;color:#fff;font-size:10px}.task-copy{display:flex;flex:1;flex-direction:column;gap:4px}.task-copy small,.updated{color:#64748b;font-size:11px}.task-progress{display:flex;align-items:center;gap:8px;font-size:11px}.task-progress i{display:block;width:90px;height:5px;border-radius:9px;background:#e4eaf2;overflow:hidden}.task-progress em{display:block;height:100%;background:#2563eb}.task-detail{padding:16px;border-top:1px solid #e4eaf2;background:#f9fbfe}.detail-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}.detail-grid>div{padding:10px;border-radius:9px;background:#fff}.detail-grid span{display:block;color:#64748b;font-size:10px}.detail-grid strong{display:block;margin-top:5px;font-size:12px}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}.employee-update{padding:11px;border-left:3px solid #2563eb;background:#eef5ff;font-size:12px}.decision-box,.delivery-box{margin-top:12px;padding:16px;border:1px solid #f3d48a;border-radius:12px;background:#fffaf0}.decision-box h3,.delivery-box h3{margin:7px 0;font-size:15px}.decision-box p,.delivery-box p{color:#64748b;font-size:12px}.decision-options,.inline-answer{display:flex;gap:8px;margin-top:10px}.inline-answer input{flex:1}.blocked-box{margin-top:12px;padding:12px;border-radius:10px;background:#fff1f2;color:#991b1b}.timeline{margin:16px 0 0;padding:0;list-style:none}.timeline li{display:flex;gap:10px;padding:7px 0}.timeline li i{width:8px;height:8px;margin-top:5px;border-radius:50%;background:#2563eb}.timeline li div{display:flex;flex-direction:column}.timeline li strong{font-size:11px}.timeline li span{color:#64748b;font-size:11px}.empty-state{display:flex;min-height:180px;align-items:center;justify-content:center;flex-direction:column;gap:7px;color:#64748b}.empty-state i{font-size:32px;color:#059669}.empty-state strong{color:#172033}
.task-card.status-cancel_requested{border-left-color:#ea580c}.task-card.status-cancelled{border-left-color:#64748b}.stopping-box{display:flex;flex-direction:column;gap:5px;margin-top:12px;padding:12px;border-radius:10px;background:#fff7ed;color:#9a3412;font-size:12px}.control-box{display:flex;flex-direction:column;gap:9px;margin-top:12px;padding:16px;border:1px solid #dbe4ef;border-radius:12px;background:#fff}.control-box p{margin:6px 0 0;color:#64748b;font-size:12px}.control-actions{display:flex;gap:8px}.control-actions select{flex:1}
.audit-board{margin-top:12px;padding:16px;border:1px solid #cad7e7;border-radius:14px;background:linear-gradient(145deg,#f8fbff,#f3f7fc)}.audit-board-title{display:flex;align-items:center;justify-content:space-between;gap:12px}.audit-board-title h3{margin:5px 0 0;font-size:15px}.attempt-chip{padding:5px 9px;border:1px solid #cbd8e8;border-radius:999px;background:#fff;color:#475569;font-size:10px;font-weight:700}.audit-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:13px}.audit-section{min-width:0;padding:12px;border:1px solid #dce5f0;border-radius:11px;background:rgba(255,255,255,.88)}.audit-section>header{display:flex;align-items:center;justify-content:space-between;margin-bottom:9px}.audit-section>header strong{font-size:12px}.audit-section>header span{color:#64748b;font-size:10px}.audit-list{display:flex;flex-direction:column;gap:8px;margin:0;padding:0;list-style:none}.audit-item{padding:10px;border:1px solid #e1e8f1;border-radius:9px;background:#fff}.audit-item.historical{opacity:.72}.audit-item-head,.audit-item-head>div,.outcome-row,.compensation-row{display:flex;align-items:center;gap:7px}.audit-item-head{justify-content:space-between}.audit-item-head strong{font-size:11px}.audit-item-head small{color:#64748b;font-size:9px}.status-pill,.outcome-row span,.compensation-row>span{padding:3px 6px;border-radius:999px;font-size:9px;font-weight:800}.is-pass{background:#dcfce7!important;color:#166534!important}.is-running{background:#dbeafe!important;color:#1d4ed8!important}.is-warning{background:#fef3c7!important;color:#92400e!important}.is-fail{background:#fee2e2!important;color:#991b1b!important}.audit-item dl{display:grid;grid-template-columns:1fr 1fr;gap:6px 9px;margin:9px 0 0}.audit-item dl div{min-width:0}.audit-item dt{color:#94a3b8;font-size:9px}.audit-item dd{margin:2px 0 0;overflow:hidden;color:#334155;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.check-list{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.check-list span{padding:3px 6px;border-radius:6px;font-size:9px;font-weight:700}.check-pass{background:#ecfdf5;color:#047857}.check-fail{background:#fff1f2;color:#be123c}.audit-error,.audit-note{margin:8px 0 0;padding:6px 7px;border-radius:6px;font-size:10px}.audit-error{background:#fff1f2;color:#be123c}.audit-note{background:#f1f5f9;color:#475569}.audit-empty{margin:0;padding:14px 8px;color:#94a3b8;font-size:10px;text-align:center}.outcome-row{margin-top:8px}.compensation-row{justify-content:space-between;margin-top:8px}.compensation-row small{color:#64748b;font-size:9px}.compensation-ok{background:#dcfce7;color:#166534}.compensation-ready{background:#dbeafe;color:#1d4ed8}.compensation-risk{background:#fee2e2;color:#991b1b}.verification-gate{display:flex;align-items:flex-start;gap:10px;margin:11px 0;padding:10px;border-radius:9px}.verification-gate i{margin-top:1px;font-size:18px}.verification-gate div{display:flex;min-width:0;flex:1;flex-direction:column;gap:2px}.verification-gate strong{font-size:11px}.verification-gate span{overflow:hidden;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.gate-blockers{display:flex;flex-direction:column;gap:3px;margin:6px 0 0;padding-left:17px;font-size:10px}.gate-blockers li{line-height:1.35}.gate-pass{background:#ecfdf5;color:#065f46}.gate-blocked{background:#fff7ed;color:#9a3412}
@media(max-width:1200px){.audit-grid{grid-template-columns:1fr}.audit-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:900px){.summary-grid{grid-template-columns:1fr 1fr}.create-grid{grid-template-columns:1fr}.span-two{grid-column:auto}.detail-grid{grid-template-columns:1fr 1fr}.task-progress{display:none}.employee-inbox{padding:16px}.audit-list{display:flex}.audit-board-title{align-items:flex-start;flex-direction:column}}
</style>
