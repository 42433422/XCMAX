import { getCurrentInstance, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { authApi } from '@/api/auth'
import agentRunsApi, { type AgentRun } from '@/api/agentRuns'
import { catalogPricesApi, type CatalogEditRequest, type CatalogObservation, type CatalogProduct, type CatalogSource } from '@/api/catalogPrices'
import { useModsStore } from '@/stores/mods'
import { getApiBase } from '@/utils/apiBase'
import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { runHasUncertainReceipt } from '@/utils/agentRunExecution'
import { requiresTurnReconciliation } from '@/composables/chat-orchestration/chatOrchestrationShared'

export interface Draft {
  action: CatalogEditRequest['action']; price: string; period_start: string; period_end: string
  selected_sources: string[]; reason: string; confirmed: boolean
}
interface Original {
  id: number; operation: string; digest: string; source: CatalogSource; runId: string; approvalSent: boolean
}
export interface Status {
  state: 'unknown' | 'pending' | 'verified'; message: string; operation?: string; runId?: string; canApprove?: boolean; canReconcile?: boolean
  preview?: { action: string; price: string; period_start: string | null; period_end: string | null; reason: string; currency: string; price_unit: string; observations: Pick<CatalogObservation, 'source_key' | 'price' | 'period_start' | 'period_end'>[] }
}
const PREFIX = 'xcagi-catalog-price-operation-v1:'
const RECONCILE_PERMISSIONS = ['product.view', 'dataset.read', 'etl.execute', 'product.edit', 'dataset.write', 'etl.template.manage']
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const HASH = /^[0-9a-f]{64}$/
const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const sameSource = (a: CatalogSource, b: CatalogSource) => !!a && !!b && a.source_id === b.source_id && a.epoch === b.epoch && a.protocol === b.protocol
const sourceValid = (s: CatalogSource) => !!s && s.protocol === 'etl-owned-mixed-v1' && ['source_id', 'epoch', 'protocol'].every(k => typeof s[k as keyof CatalogSource] === 'string' && !!s[k as keyof CatalogSource])
const observation = (o: Pick<CatalogObservation, 'source_key' | 'price' | 'period_start' | 'period_end'>) => ({ source_key: o.source_key, price: o.price, period_start: o.period_start, period_end: o.period_end })
/** Stable client subset; a run cannot swap approval content after a lost response. */
async function digest(params: Record<string, unknown>) {
  if (!globalThis.crypto?.subtle) throw new Error('安全摘要不可用，未提交')
  const value = {
    operation_id: params.operation_id, revision: params.revision, action: params.action, price: params.price,
    period_start: params.period_start, period_end: params.period_end, selected_sources: params.selected_sources,
    reason: params.reason, confirmed: params.confirmed, product_id: params.product_id,
    currency: params.currency, price_unit: params.price_unit,
    selected_observations: (params.selected_observations as CatalogObservation[]).map(observation),
  }
  const bytes = new TextEncoder().encode(JSON.stringify(value))
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), x => x.toString(16).padStart(2, '0')).join('')
}
export function catalogPeriod(start: string | null, end: string | null): string {
  return start === null && end === null ? '未标注期间' : `${start ?? '未标注起日'} 至 ${end ?? '未标注止日'}`
}
function validDate(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
}

/** Protected mixed catalog only. Legacy ERP is never used as a write/readback fallback. */
export function useAssistantCatalogPrices(onVerified: (id: number) => void) {
  const mods = useModsStore()
  const selected = ref(false), loading = ref(false), error = ref('')
  const rows = ref<CatalogProduct[]>([]), drafts = ref<Record<number, Draft>>({})
  const statuses = ref<Record<number, Status>>({}), busyId = ref<number | null>(null)
  let generation = 0, searchSequence = 0
  const identity = () => {
    const input = getRuntimeTenantStorageScopeInput()
    const tenant = Number(input?.tenantId), user = String(input?.localUserId ?? ''), mod = String(mods.activeModId || '')
    return Number.isSafeInteger(tenant) && tenant > 0 && /^[1-9]\d*$/.test(user) && mod ? { tenant, user, mod, base: getApiBase() } : null
  }
  const scopeKey = () => JSON.stringify(identity())
  const key = (id: number) => `${PREFIX}${encodeURIComponent(scopeKey())}:${id}`
  const capture = () => ({ scope: scopeKey(), epoch: productReadAccountEpoch.value, generation, identity: identity() })
  const reconciliation = ref<{ id: number; operation: string; context: ReturnType<typeof capture> } | null>(null)
  const current = (s: ReturnType<typeof capture>) => selected.value && !!s.identity && s.scope === scopeKey() && s.epoch === productReadAccountEpoch.value && s.generation === generation
  const show = (id: number, value: Status) => { statuses.value = { ...statuses.value, [id]: value } }
  const original = (id: number): Original | null => {
    const raw = localStorage.getItem(key(id))
    if (!raw) return null
    const value = JSON.parse(raw) as Original
    if (value.id !== id || !UUID.test(value.operation) || !HASH.test(value.digest) || !sourceValid(value.source) || typeof value.runId !== 'string' || typeof value.approvalSent !== 'boolean') throw new Error('原操作标记不可核验')
    return value
  }
  const persist = (value: Original) => {
    const data = JSON.stringify(value), storageKey = key(value.id)
    localStorage.setItem(storageKey, data)
    if (localStorage.getItem(storageKey) !== data) throw new Error('原操作无法持久保存，未提交')
  }
  function statusFor(id: number): Status | undefined {
    try {
      const saved = original(id)
      if (saved) {
        const status = statuses.value[id]
        if (status && status.operation === saved.operation && status.state !== 'verified') return { ...status, canApprove: !!status.canApprove && !saved.approvalSent }
        return { state: 'unknown', operation: saved.operation, runId: saved.runId, message: '原操作结果待核对，禁止重复提交。' }
      }
      return statuses.value[id]
    } catch { return { state: 'unknown', message: '原操作标记不可核验，禁止重复提交。' } }
  }
  const draftFor = (id: number) => drafts.value[id]
  function resetDraft(row: CatalogProduct) {
    drafts.value[row.id] = { action: 'append_price', price: '', period_start: '', period_end: '', selected_sources: [], reason: '', confirmed: false }
  }
  function selectMode(row: CatalogProduct, action: Draft['action']) {
    if (statusFor(row.id)?.state && statusFor(row.id)?.state !== 'verified') return
    resetDraft(row); drafts.value[row.id].action = action
  }
  function selectCorrection(row: CatalogProduct, sourceKey: string) {
    const chosen = row.history.find(h => h.source_key === sourceKey && h.effective)
    if (!chosen || !draftFor(row.id)) return
    drafts.value[row.id].selected_sources = row.history.filter(h => h.effective && h.period_start === chosen.period_start && h.period_end === chosen.period_end).map(h => h.source_key)
    drafts.value[row.id].confirmed = false
  }
  const selectedObservations = (row: CatalogProduct) => row.history.filter(h => draftFor(row.id)?.selected_sources.includes(h.source_key))
  function validRow(row: CatalogProduct, source: CatalogSource) {
    return Number.isSafeInteger(row.id) && row.id > 0 && sameSource(row.source, source) && HASH.test(row.revision)
      && typeof row.currency === 'string' && !!row.currency && typeof row.price_unit === 'string' && !!row.price_unit && Array.isArray(row.history)
  }
  async function search(keyword: string) {
    const s = capture(), seq = ++searchSequence
    if (!current(s)) { error.value = '请先登录并明确选择受保护目录。'; return }
    loading.value = true; error.value = ''; rows.value = []; drafts.value = {}; reconciliation.value = null
    try {
      if (keyword.trim().length > 100) throw new Error('关键词最多 100 字')
      const response = await catalogPricesApi.list(keyword.trim(), s.identity!.mod)
      if (!current(s) || seq !== searchSequence) return
      if (!response.success || response.capability !== 'catalog_prices_v1' || !sourceValid(response.source) || !Array.isArray(response.data) || !response.data.every(row => validRow(row, response.source))) throw new Error('受保护来源不可核验')
      rows.value = response.data
      rows.value.forEach(resetDraft)
    } catch (e) {
      if (current(s) && seq === searchSequence) error.value = e instanceof Error ? e.message : '受保护目录不可用；不会切换到 ERP 或自动建库。'
    } finally { if (current(s) && seq === searchSequence) loading.value = false }
  }
  async function locked(id: number, fn: () => Promise<void>) {
    if (!identity() || !navigator.locks?.request) throw new Error('登录身份或跨窗口保护不可用，未提交')
    await navigator.locks.request(key(id), { ifAvailable: true }, async lock => {
      if (!lock) throw new Error('另一窗口正在处理，请只读核对原操作')
      await fn()
    })
  }
  function request(row: CatalogProduct): CatalogEditRequest {
    const draft = draftFor(row.id)
    if (!draft || !draft.confirmed || !draft.reason.trim() || draft.reason.trim().length > 500) throw new Error('请填写原因并明确确认价格变更')
    if (!/^\d+(\.\d{1,2})?$/.test(draft.price.trim())) throw new Error('金额须为非负十进制，最多两位小数')
    const [whole, decimal = ''] = draft.price.trim().split('.')
    const price = `${whole.replace(/^0+(?=\d)/, '')}.${decimal.padEnd(2, '0')}`
    if (price.split('.')[0].length > 8) throw new Error('金额不得超过 99,999,999.99')
    let start: string | null = draft.period_start, end: string | null = draft.period_end
    let sources: string[] = []
    if (draft.action === 'correct_price') {
      const observations = selectedObservations(row)
      if (!observations.length || observations.some(o => !o.effective)) throw new Error('请选择原期间的有效来源观察')
      start = observations[0].period_start; end = observations[0].period_end
      const all = row.history.filter(h => h.effective && h.period_start === start && h.period_end === end)
      if (observations.length !== all.length || observations.some(o => o.period_start !== start || o.period_end !== end)) throw new Error('同期间冲突来源必须一起核对，不得改写期间')
      sources = observations.map(o => o.source_key)
    } else if (!validDate(start) || !validDate(end) || start >= end) throw new Error('新增价格必须明确填写有效起止日期，不能推测日期')
    return { operation_id: crypto.randomUUID(), revision: row.revision, action: draft.action, price, period_start: start, period_end: end, selected_sources: sources, reason: draft.reason.trim(), confirmed: true }
  }
  async function submit(row: CatalogProduct) {
    const s = capture()
    if (!current(s) || busyId.value !== null) return
    busyId.value = row.id
    try {
      await locked(row.id, async () => {
        if (!current(s)) return
        if (original(row.id)) throw new Error('已有原操作待核对，禁止重复提交')
        if (!rows.value.includes(row) || !validRow(row, row.source)) throw new Error('产品快照已失效，请重新查询')
        const body = request(row)
        const saved: Original = { id: row.id, operation: body.operation_id, digest: await digest({ ...body, product_id: row.id, currency: row.currency, price_unit: row.price_unit, selected_observations: selectedObservations(row).map(observation) }), source: { ...row.source }, runId: '', approvalSent: false }
        if (!current(s)) return
        persist(saved)
        show(row.id, { state: 'unknown', operation: saved.operation, message: '原操作已登记，等待审批任务；请勿重复提交。' })
        const response = await catalogPricesApi.submit(row.id, body, s.identity!.mod)
        if (!current(s)) return
        if (response.data?.run_id) { saved.runId = response.data.run_id; persist(saved) }
        show(row.id, { state: 'unknown', operation: saved.operation, runId: saved.runId, message: '请核对原操作内容并明确审批；尚未确认保存成功。' })
      })
    } catch (e) {
      if (current(s)) {
        const prior = statusFor(row.id)
        const detail = e instanceof Error ? e.message : '请核对原操作。'
        show(row.id, { state: 'unknown', operation: prior?.operation, runId: prior?.runId, message: prior?.operation ? `结果未知（UNKNOWN），禁止重放。${detail}` : detail })
      }
    } finally { if (current(s)) busyId.value = null }
  }
  function uncertain(run: AgentRun) {
    return run.metadata?.non_retryable === true || runHasUncertainReceipt(run)
      || requiresTurnReconciliation(run.final_output) || requiresTurnReconciliation(run.metadata?.recovery)
      || (run.steps || []).some(step => requiresTurnReconciliation(step.output) || requiresTurnReconciliation(step.output?.business_verification))
  }
  async function canReconcile(s: ReturnType<typeof capture>) {
    try {
      const response = await authApi.getCurrentUser()
      return current(s) && response.success && String(response.data?.user?.id) === s.identity!.user
        && Array.isArray(response.data?.permissions) && RECONCILE_PERMISSIONS.every(p => response.data!.permissions.includes(p))
    } catch { return false }
  }
  function requestReconciliation(row: CatalogProduct) {
    if (busyId.value !== null || !rows.value.includes(row) || !statusFor(row.id)?.canReconcile) return
    const context = capture(), saved = original(row.id)
    if (current(context) && saved) reconciliation.value = { id: row.id, operation: saved.operation, context }
  }
  const reconciliationFor = (id: number) => reconciliation.value?.id === id ? reconciliation.value.operation : undefined
  const cancelReconciliation = () => { reconciliation.value = null }
  async function confirmReconciliation(row: CatalogProduct) {
    const confirmation = reconciliation.value
    cancelReconciliation()
    if (!confirmation || confirmation.id !== row.id || !current(confirmation.context) || !rows.value.includes(row)) return
    await check(row, false, confirmation)
  }
  async function check(row: CatalogProduct, approve = false, confirmation?: NonNullable<typeof reconciliation.value>) {
    const s = capture()
    if (!current(s) || busyId.value !== null) return
    busyId.value = row.id
    try {
      await locked(row.id, async () => {
        if (!current(s)) return
        const saved = original(row.id)
        if (!saved) return
        if (confirmation && (!current(confirmation.context) || saved.operation !== confirmation.operation)) throw new Error('原核对确认已失效')
        const response = await catalogPricesApi.lookup(saved.operation, s.identity!.mod)
        if (!current(s)) return
        const run = response.data, operation = response.operation
        const context = object(run?.metadata?.runtime_context)
        if (!response.success || !run || !operation || operation.operation_id !== saved.operation || operation.run_id !== run.run_id || !HASH.test(operation.request_digest)
          || (saved.runId && saved.runId !== run.run_id) || String(run.user_id) !== s.identity!.user
          || String(context.tenant_id) !== String(s.identity!.tenant) || context.mod_id !== s.identity!.mod
          || run.steps?.length !== 1 || !sameSource(row.source, saved.source)) throw new Error('原操作身份、任务或来源代次不一致')
        const step = run.steps[0], params = object(step.params)
        if (step.tool_id !== 'catalog_products_v1' || step.action !== params.action || !['append_price', 'correct_price'].includes(step.action)
          || params.operation_id !== saved.operation || params.product_id !== row.id || await digest(params) !== saved.digest) throw new Error('原审批内容与提交摘要不一致')
        if (!current(s)) return
        saved.runId = run.run_id; persist(saved)
        const preview: NonNullable<Status['preview']> = {
          action: step.action, price: String(params.price), period_start: params.period_start as string | null,
          period_end: params.period_end as string | null, reason: String(params.reason),
          currency: String(params.currency), price_unit: String(params.price_unit),
          observations: (params.selected_observations as CatalogObservation[]).map(observation),
        }
        if (!confirmation && run.status === 'waiting_user') {
          const approval = response.approval
          const eligible = operation.state === 'pending' && !saved.approvalSent && !uncertain(run) && step.status === 'waiting_user'
            && !(run.tool_calls || []).length && !Object.keys(object(step.output)).length
            && approval?.run_id === saved.runId && approval.step_id === step.step_id
            && approval.tool_id === step.tool_id && approval.action === step.action && !!approval.grant
          if (approve && eligible) {
            saved.approvalSent = true; persist(saved)
            show(row.id, { state: 'unknown', operation: saved.operation, runId: saved.runId, preview, message: '审批已提交；仅可核对原操作，不得重复执行。' })
            await agentRunsApi.continueRun(saved.runId, { approval_grant: approval!.grant }, s.identity!.mod)
            return
          }
          show(row.id, { state: eligible ? 'pending' : 'unknown', operation: saved.operation, runId: saved.runId, canApprove: eligible, preview, message: eligible ? '等待明确审批，尚未保存。请核对原金额、新金额、期间及原因。' : '原审批结果未知，禁止重新审批或重放。' })
          if (eligible) return
        }
        // GET only observes history. Only an explicitly confirmed POST may finalize a pending HOST head.
        if (confirmation && !await canReconcile(s)) throw new Error('当前会话无完整核对权限；原操作保留，只可读取')
        if (!current(s)) return
        if (!rows.value.includes(row) || !sameSource(row.source, saved.source)) throw new Error('原目录快照已失效，保留原操作')
        let verified
        try {
          verified = confirmation
            ? await catalogPricesApi.reconcile(saved.operation, s.identity!.mod)
            : await catalogPricesApi.verify(saved.operation, s.identity!.mod)
        } catch (e) {
          if (confirmation || object(e).status !== 409 || !['pending', 'resolving_no_effect'].includes(operation.state)) throw e
          // The original identity was independently checked above. A missing
          // receipt is NOT absence proof: only offer an explicit server decision.
          const permitted = await canReconcile(s)
          if (!current(s)) return
          if (!rows.value.includes(row) || !sameSource(row.source, saved.source)) throw new Error('原目录快照已失效，保留原操作')
          show(row.id, { state: 'unknown', operation: saved.operation, runId: saved.runId, preview, canReconcile: permitted,
            message: `原操作结果仍未知，保留标记，禁止重放；未证明已保存或无副作用。${permitted ? '可明确确认核对并终结原操作；服务器无法核验时仍会保留。' : '当前会话只可读取，不能执行核对确认。'}` })
          return
        }
        if (!current(s)) return
        if (!rows.value.includes(row) || !sameSource(row.source, saved.source)) throw new Error('原目录快照已失效，保留原操作')
        const proof = verified.data
        if (!verified.success || proof?.verified !== true || proof.operation_id !== saved.operation || proof.run_id !== saved.runId || proof.request_digest !== operation.request_digest
          || typeof proof.business_action_id !== 'string' || !proof.business_action_id
          || proof.product?.id !== row.id || !validRow(proof.product, saved.source) || typeof proof.current_matches !== 'boolean') throw new Error('同来源独立读回未核验，禁止重放')
        const rejected = proof.outcome === 'rejected_no_effect'
        const preclaim = proof.receipt_kind === 'catalog_preclaim_finalization_v1'
        if (!['saved', 'rejected_no_effect'].includes(proof.outcome) || proof.fresh_save !== false || proof.historical_effect_verified !== !rejected
          || (preclaim ? !rejected || proof.reason_code !== 'preclaim_finalized' : proof.receipt_kind !== undefined || (rejected && proof.reason_code !== 'review_precondition_changed'))
          || (rejected && proof.current_matches !== false)) throw new Error('原操作历史或无副作用证明不完整，禁止重放')
        const terminal = operation.state === (preclaim ? 'finalized_no_effect' : rejected ? 'rejected' : 'verified')
        if (!confirmation && !terminal) {
          const permitted = await canReconcile(s)
          if (!current(s)) return
          show(row.id, { state: 'unknown', operation: saved.operation, runId: saved.runId, preview, canReconcile: permitted,
            message: `${rejected ? '原操作已核验无副作用' : proof.current_matches ? '历史修改已核验，当前读回一致' : '历史修改已核验，当前数据已有后续变更'}；HOST 原操作尚未终结，保留标记，禁止重放。${permitted ? '可明确确认核对原操作。' : '当前会话只可读取，不能执行核对确认。'}` })
          return
        }
        // Clear only after terminal HOST + valid receipt, or explicit POST + valid receipt.
        localStorage.removeItem(key(row.id))
        if (localStorage.getItem(key(row.id)) !== null) throw new Error('原操作标记无法更新')
        rows.value = rows.value.map(item => item.id === row.id ? proof.product : item)
        resetDraft(proof.product)
        show(row.id, { state: 'verified', operation: saved.operation, runId: saved.runId, message: preclaim ? '未保存：原操作已核验并终结，请重新核对再提交' : rejected ? '未保存：审核前态已变化，请重新核对再提交' : proof.current_matches ? '历史修改已核验，同来源当前读回一致；本次未重新保存。' : '历史修改已核验，当前数据已有后续变更；已刷新最新版本，本次未重新保存。' })
        if (!rejected && proof.current_matches) onVerified(row.id)
      })
    } catch (e) {
      if (current(s)) {
        const prior = statusFor(row.id)
        show(row.id, { state: 'unknown', operation: prior?.operation, runId: prior?.runId, message: `结果未知（UNKNOWN），禁止重放。${e instanceof Error ? e.message : '请核对原操作。'}` })
      }
    } finally { if (current(s)) busyId.value = null }
  }
  function canEdit(row: CatalogProduct) {
    if (!selected.value || busyId.value !== null) return false
    try { return original(row.id) === null } catch { return false }
  }
  const clear = () => {
    generation++; searchSequence++; reconciliation.value = null; rows.value = []; drafts.value = {}; statuses.value = {}; busyId.value = null; loading.value = false; error.value = ''
  }
  watch(() => [scopeKey(), productReadAccountEpoch.value], () => { selected.value = false; clear() }, { flush: 'sync' })
  watch(selected, clear, { flush: 'sync' })
  if (getCurrentInstance()) {
    const storageChanged = (event: StorageEvent) => {
      if (!event.key || event.key.startsWith(PREFIX)) statuses.value = {}
    }
    onMounted(() => window.addEventListener('storage', storageChanged))
    onBeforeUnmount(() => { clear(); window.removeEventListener('storage', storageChanged) })
  }
  return { selected, loading, error, rows, drafts, busyId, search, submit, check, requestReconciliation, reconciliationFor, confirmReconciliation, cancelReconciliation, statusFor, draftFor, canEdit, selectMode, selectCorrection, selectedObservations, period: catalogPeriod }
}
