import { getCurrentInstance, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import agentRunsApi, { type AgentRun } from '@/api/agentRuns'
import productsApi from '@/api/products'
import { useModsStore } from '@/stores/mods'
import { getApiBase } from '@/utils/apiBase'
import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { runHasUncertainReceipt } from '@/utils/agentRunExecution'
import { requiresTurnReconciliation } from '@/composables/chat-orchestration/chatOrchestrationShared'
import type { AssistantProductRow } from './useAssistantFloatState'

type SavedReceipt = { productId: number; requestDigest: string; runId: string; approvalSent: boolean }
type EditStatus = { state: 'unknown' | 'pending' | 'verified'; message: string; runId?: string; canApprove?: boolean }

function normalize(value: Partial<AssistantProductRow>) {
  const id = Number(value.id)
  const price = Number(value.price)
  if (!Number.isSafeInteger(id) || id <= 0 || !Number.isFinite(price) || price < 0) throw new Error('产品编号或价格无效')
  return { id, model_number: String(value.model_number || '').trim(), name: String(value.name || '').trim(), price, unit: String(value.unit || '').trim() }
}
async function requestDigest(row: Partial<AssistantProductRow>): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error('当前环境无法安全核对请求，请勿提交')
  const bytes = new TextEncoder().encode(JSON.stringify(normalize(row)))
  return Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes)), x => x.toString(16).padStart(2, '0')).join('')
}
function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

/** One durable, account-scoped original request; no unconfirmed write is retried. */
export function useAssistantProductEdit(onVerified: (id: number) => void) {
  const mods = useModsStore()
  const statuses = ref<Record<number, EditStatus>>({})
  const busyId = ref<number | null>(null)
  let scopeVersion = 0
  const identity = () => {
    const account = getRuntimeTenantStorageScopeInput()
    const tenant = Number(account?.tenantId)
    const owner = String(account?.localUserId ?? '').trim()
    const mod = String(mods.activeModId || '').trim()
    if (!Number.isSafeInteger(tenant) || tenant <= 0 || !/^[1-9]\d*$/.test(owner) || !mod) return null
    return { tenant, owner, mod, base: getApiBase() }
  }
  const scopeKey = () => JSON.stringify(identity())
  const keyFor = (id: number) => `xcagi-product-edit-receipt-v1:${encodeURIComponent(scopeKey())}:${id}`
  const capture = () => ({ identity: identity(), key: scopeKey(), epoch: productReadAccountEpoch.value, version: scopeVersion })
  const current = (scope: ReturnType<typeof capture>) => !!scope.identity && scope.key === scopeKey() && scope.epoch === productReadAccountEpoch.value && scope.version === scopeVersion
  const show = (id: number, status: EditStatus) => { statuses.value = { ...statuses.value, [id]: status } }
  const load = (id: number): SavedReceipt | null => {
    const raw = localStorage.getItem(keyFor(id))
    if (!raw) return null
    const value = JSON.parse(raw) as SavedReceipt
    if (value.productId !== id || !/^[0-9a-f]{64}$/.test(value.requestDigest) || typeof value.runId !== 'string' || typeof value.approvalSent !== 'boolean') throw new Error('原保存记录不可核验，请勿重复提交')
    return value
  }
  const persist = (receipt: SavedReceipt) => {
    const key = keyFor(receipt.productId)
    const data = JSON.stringify(receipt)
    localStorage.setItem(key, data)
    if (localStorage.getItem(key) !== data) throw new Error('无法保存原请求核对标记，请勿提交')
  }
  const statusFor = (id: number): EditStatus | undefined => {
    try {
      const saved = load(id)
      if (saved) {
        const cached = statuses.value[id]
        if (cached && cached.state !== 'verified' && (!cached.runId || cached.runId === saved.runId)) {
          return saved.approvalSent ? { ...cached, canApprove: false } : cached
        }
        return { state: 'unknown', runId: saved.runId, message: '原保存结果待核对，禁止重复提交。' }
      }
    } catch { return { state: 'unknown', message: '原保存记录不可核验，禁止重复提交。' } }
    return statuses.value[id]
  }
  async function locked<T>(id: number, fn: () => Promise<T>): Promise<T> {
    if (!identity() || !navigator.locks?.request) throw new Error('登录身份或跨窗口保护不可用，未提交保存')
    return navigator.locks.request(keyFor(id), { ifAvailable: true }, async lock => {
      if (!lock) throw new Error('原保存正在处理中，请勿重复提交')
      return fn()
    })
  }
  function validRun(run: AgentRun, saved: SavedReceipt, scope: NonNullable<ReturnType<typeof identity>>) {
    const context = record(run.metadata?.runtime_context)
    const steps = run.steps || []
    return run.run_id === saved.runId && String(run.user_id) === scope.owner
      && String(context.tenant_id) === String(scope.tenant) && String(context.mod_id || '') === scope.mod
      && steps.length === 1 && steps[0].tool_id === 'products' && steps[0].action === 'update'
      && Number(steps[0].params?.id) === saved.productId
  }
  async function lookup(id: number, scope: ReturnType<typeof capture>, saved: SavedReceipt, approve = false) {
    if (!saved.runId || !scope.identity) { show(id, { state: 'unknown', message: '未收到原任务编号，请独立核对，禁止重复提交。' }); return }
    const response = await agentRunsApi.getRun(saved.runId)
    if (!current(scope)) return
    const run = response.data
    if (!response.success || !run || !validRun(run, saved, scope.identity)) throw new Error('原任务身份或产品不一致')
    const step = run.steps![0]
    if (await requestDigest(step.params as Partial<AssistantProductRow>) !== saved.requestDigest || !current(scope)) throw new Error('原任务内容与提交摘要不一致')
    if (run.status === 'waiting_user') {
      const approval = response.approval
      // A stale waiting_user label is not proof that dispatch never started.
      // Reconcile any execution evidence instead of consuming another grant.
      const eligible = !saved.approvalSent && step.status === 'waiting_user'
        && !(run.tool_calls || []).length && !Object.keys(record(step.output)).length
        && run.metadata?.non_retryable !== true
        && !runHasUncertainReceipt(run)
        && !requiresTurnReconciliation(run.final_output)
        && !requiresTurnReconciliation(record(run.final_output).business_verification)
        && !requiresTurnReconciliation(run.metadata?.recovery)
        && approval?.run_id === saved.runId && approval?.step_id === step.step_id && approval?.tool_id === 'products' && approval?.action === 'update' && !!approval?.grant
      if (approve && eligible) {
        saved.approvalSent = true
        persist(saved) // Claim before consuming the server-issued approval grant.
        show(id, { state: 'unknown', runId: saved.runId, message: '审批已提交，执行结果待核对，请勿重复提交。' })
        await agentRunsApi.continueRun(saved.runId, { approval_grant: approval!.grant })
        if (!current(scope)) return
        show(id, { state: 'unknown', runId: saved.runId, message: '审批已提交，请只读核对原任务和产品，勿重复执行。' })
      } else {
        show(id, { state: 'pending', runId: saved.runId, canApprove: !!eligible, message: eligible ? '原修改等待审批，尚未保存。' : '原审批结果待核对，禁止重复提交。' })
      }
      return
    }
    const calls = (run.tool_calls || []).filter(call => call.step_id === step.step_id && call.tool_id === 'products' && call.action === 'update')
    const call = calls[0]
    const stepAction = String(step.output?.business_action_id || '')
    if (run.status !== 'completed' || step.status !== 'completed' || step.output?.success !== true
      || record(step.output?.business_verification).verified !== true
      || calls.length !== 1 || !call?.call_id || call.status !== 'completed' || call.output?.success !== true
      || !step.node_id || call.node_id !== step.node_id || !stepAction || call.output?.business_action_id !== stepAction
      || record(call.output?.business_verification).verified !== true || requiresTurnReconciliation(call.output) || requiresTurnReconciliation(call.output?.business_verification)
      || run.metadata?.non_retryable === true || runHasUncertainReceipt(run)
      || requiresTurnReconciliation(step.output) || requiresTurnReconciliation(step.output?.business_verification)
      || requiresTurnReconciliation(run.final_output) || requiresTurnReconciliation(run.metadata?.recovery)) {
      show(id, { state: 'unknown', runId: saved.runId, message: '原任务尚无可信完成回执，请继续核对，禁止重复提交。' })
      return
    }
    if (await requestDigest(record(record(call).params)) !== saved.requestDigest || !current(scope)) throw new Error('工具调用内容与原请求不一致')
    const actual = await productsApi.getProduct(id)
    if (!current(scope)) return
    if (actual.success !== true || !actual.data || await requestDigest(actual.data) !== saved.requestDigest || !current(scope)) throw new Error('产品独立读回不一致')
    localStorage.removeItem(keyFor(id))
    if (localStorage.getItem(keyFor(id)) !== null) throw new Error('原核对标记无法更新')
    show(id, { state: 'verified', runId: saved.runId, message: '保存已完成，原任务回执和产品独立读回一致。' })
    onVerified(id)
  }
  async function saveProductRow(row: AssistantProductRow) {
    const id = Number(row?.id)
    if (!id) return
    const scope = capture()
    if (!current(scope)) { show(id, { state: 'unknown', message: '请先登录并确认当前租户。' }); return }
    busyId.value = id
    try {
      await locked(id, async () => {
        if (!current(scope)) return
        if (load(id)) { show(id, { state: 'unknown', message: '已有原保存待核对，禁止重复提交。' }); return }
        const data = normalize(row)
        const saved = { productId: id, requestDigest: await requestDigest(data), runId: '', approvalSent: false }
        if (!current(scope)) return
        persist(saved)
        show(id, { state: 'unknown', message: '已提交保存，等待原任务回执；请勿重复提交。' })
        const response = await productsApi.updateProduct(id, data)
        if (!current(scope)) return
        const result = record(response)
        const runId = String(result.run_id || result.agent_run_id || '')
        if (runId && /^[a-zA-Z0-9_-]{1,128}$/.test(runId)) { saved.runId = runId; persist(saved) }
        show(id, { state: result.pending_approval === true || result.agent_status === 'waiting_user' ? 'pending' : 'unknown', runId: saved.runId, message: saved.runId ? '原保存已建立任务，请只读核对审批和回执。' : '未收到原任务编号，请独立核对，禁止重复提交。' })
      })
    } catch (error) {
      if (current(scope)) show(id, { state: 'unknown', message: '保存结果待核对，请勿重复提交。' })
      throw error
    } finally { if (current(scope)) busyId.value = null }
  }
  async function checkProductRow(row: AssistantProductRow, approve = false) {
    const id = Number(row?.id), scope = capture()
    if (!id || !current(scope)) return
    busyId.value = id
    try {
      await locked(id, async () => {
        if (!current(scope)) return
        const saved = load(id)
        if (!saved) return
        await lookup(id, scope, saved, approve)
      })
    } catch {
      if (current(scope)) show(id, { state: 'unknown', message: '原任务或产品读回不可核验，请勿重复提交。' })
    } finally { if (current(scope)) busyId.value = null }
  }
  watch(() => [scopeKey(), productReadAccountEpoch.value], () => { scopeVersion++; statuses.value = {}; busyId.value = null }, { flush: 'sync' })
  if (getCurrentInstance()) {
    const onStorage = (event: StorageEvent) => {
      if (!event.key || event.key.startsWith('xcagi-product-edit-receipt-v1:')) statuses.value = {}
    }
    onMounted(() => window.addEventListener('storage', onStorage))
    onBeforeUnmount(() => window.removeEventListener('storage', onStorage))
  }
  return { saveProductRow, checkProductRow, statusFor, busyId }
}
