import type { AgentRun } from '@/api/agentRuns'
import { getApiBase } from '@/utils/apiBase'
import { runHasUncertainReceipt } from '@/utils/agentRunExecution'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { asRecord, asString } from '@/utils/typeGuards'

type Body = Record<string, unknown>
export type EmployeeRequestTransport = {
  post: (path: string, body: Body) => Promise<unknown>
  get: (path: string) => Promise<unknown>
}
const inFlight = new Map<string, Promise<Body>>()
const requestPrefix = 'xcagi_admin_employee_request:'
type RequestIdentity = { key: string; runId?: string; conflicted?: boolean }
type StoredRequest = RequestIdentity & { version: 3; bindingDigest: string }
type RequestScope = {
  ownerScope: string; server: string; epoch: number
  bindingDigest: string
}
class RequestBindingMismatch extends Error {
  constructor(readonly identity: RequestIdentity) { super('原员工请求绑定了其他账号或服务器，请核对原任务。') }
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical)
  if (value && typeof value === 'object') return Object.fromEntries(
    Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]),
  )
  return value
}

export function adminEmployeeState(result: Body): string {
  const state = asString(result.execution_state).trim().toLowerCase()
  if (!state || !asString(result.run_id) || runHasUncertainReceipt({
    status: state, final_output: result, steps: [],
  } as unknown as AgentRun)) return 'unknown'
  return state
}

export function adminEmployeeMessage(result: Body): string {
  const state = adminEmployeeState(result)
  return ({
    queued: '原任务正在排队，请稍后查看回执。', running: '原任务仍在执行，请稍后查看回执。',
    retrying: '原任务正在重试，请稍后查看回执。', waiting_approval: '原任务正在等待审批。',
    waiting_input: '原任务正在等待补充信息。', waiting_auth: '原任务正在等待授权。',
    paused: '原任务已暂停。', blocked: '原任务已阻断，请查看回执。',
    unknown: '结果待核对，请继续读取原任务回执，勿重复提交。',
  } as Record<string, string>)[state] || asString(result.message) || '员工执行失败。'
}

function ownerScope(ownerId?: number | null): string {
  const scope = getRuntimeTenantStorageScopeInput() || (ownerId ? { localUserId: ownerId } : null)
  return scope ? JSON.stringify(canonical(scope)) : ''
}
function legacyServer(): string { return getApiBase() || window.location.origin }
function currentServer(): string { return new URL(getApiBase() || '/', document.baseURI).href.replace(/\/$/, '') }
async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}
async function requestScope(scope: string, server: string, epoch: number, employeeId: string): Promise<RequestScope> {
  // One scoped commitment avoids independently correlating an employee or owner
  // across accounts/servers. Keep the original request key for GET-only recovery.
  const bindingDigest = await sha256(JSON.stringify(['admin-employee-request-binding-v3', scope, server, employeeId]))
  return { ownerScope: scope, server, epoch, bindingDigest }
}
function scopeCurrent(scope: RequestScope, ownerId?: number | null): boolean {
  return scope.ownerScope === ownerScope(ownerId) && scope.server === currentServer()
    && scope.epoch === productReadAccountEpoch.value
}
function unchanged(saved: StoredRequest, scope: RequestScope, ownerId?: number | null): boolean {
  return saved.bindingDigest === scope.bindingDigest && scopeCurrent(scope, ownerId)
}
function persistRequest(storageKey: string, saved: StoredRequest): void {
  const encoded = JSON.stringify(canonical(saved))
  localStorage.setItem(storageKey, encoded)
  if (localStorage.getItem(storageKey) !== encoded) throw new Error('无法保存员工请求身份，未提交任务。')
}
async function loadRequest(
  storageKey: string, encoded: string, scope: RequestScope, employeeId: string, ownerId?: number | null,
): Promise<StoredRequest> {
  const raw = asRecord(JSON.parse(encoded))
  if (typeof raw.key !== 'string' || !raw.key
    || (raw.runId !== undefined && (typeof raw.runId !== 'string' || !raw.runId))
    || (raw.conflicted !== undefined && typeof raw.conflicted !== 'boolean')) {
    throw new Error('原员工请求身份缺失，请核对原任务。')
  }
  const identity: RequestIdentity = { key: raw.key,
    ...(typeof raw.runId === 'string' ? { runId: raw.runId } : {}),
    ...(raw.conflicted === true ? { conflicted: true } : {}) }
  if (raw.version === 3) {
    if (typeof raw.bindingDigest !== 'string' || !/^[a-f0-9]{64}$/.test(raw.bindingDigest)) {
      throw new Error('原员工请求身份缺失，请核对原任务。')
    }
    if (raw.bindingDigest !== scope.bindingDigest) throw new RequestBindingMismatch(identity)
  } else if (raw.version === 2) {
    const expected = await Promise.all([sha256(scope.ownerScope), sha256(employeeId), sha256(legacyServer())])
    if (raw.ownerDigest !== expected[0] || raw.employeeDigest !== expected[1]
      || typeof raw.serverDigest !== 'string' || !/^[a-f0-9]{64}$/.test(raw.serverDigest)) {
      throw new Error('原员工请求身份缺失，请核对原任务。')
    }
    if (raw.serverDigest !== expected[2]) throw new RequestBindingMismatch(identity)
  } else {
    if (raw.version !== undefined || raw.ownerScope !== scope.ownerScope || raw.employeeId !== employeeId
      || typeof raw.server !== 'string' || !raw.server) throw new Error('原员工请求身份缺失，请核对原任务。')
    if (raw.server !== legacyServer()) throw new RequestBindingMismatch(identity)
  }
  const saved: StoredRequest = { version: 3, ...identity, bindingDigest: scope.bindingDigest }
  if (raw.version !== 3) {
    // Keep the original storage/request keys: migration is read-only recovery,
    // never permission to submit an already sent operation again.
    if (!scopeCurrent(scope, ownerId) || localStorage.getItem(storageKey) !== encoded) {
      throw new Error('原员工请求记录已变化，请重新读取原任务。')
    }
    persistRequest(storageKey, saved)
  }
  return saved
}
function unknown(saved: RequestIdentity): Body {
  return { success: false, execution_state: 'unknown', retryable: false, run_id: saved.runId || '',
    requires_reconciliation: true, idempotency_key: saved.key, turn_id: saved.key,
    message: '结果待核对，请在原账号和服务器读取任务回执，勿重复提交。' }
}
function conflict(): Error { return Object.assign(new Error('原请求标识与已有任务冲突，请核对原任务。'), { status: 409 }) }

function acceptReceipt(storageKey: string, saved: StoredRequest, result: Body): Body {
  if (asString(result.idempotency_key || result.turn_id) !== saved.key || !asString(result.run_id)
    || (saved.runId && saved.runId !== asString(result.run_id))) return unknown(saved)
  if (!saved.runId) {
    saved.runId = asString(result.run_id)
    try { persistRequest(storageKey, saved) } catch { return unknown(saved) }
  }
  const state = adminEmployeeState(result)
  if (['completed', 'failed', 'cancelled', 'rejected'].includes(state)) {
    if (localStorage.getItem(storageKey) === JSON.stringify(canonical(saved))) localStorage.removeItem(storageKey)
  }
  return { ...result, execution_state: state, success: state === 'completed', retryable: false }
}

async function readReceipt(
  storageKey: string, saved: StoredRequest, employeeId: string, scope: RequestScope,
  transport: EmployeeRequestTransport, ownerId?: number | null,
): Promise<Body> {
  if (saved.conflicted || !unchanged(saved, scope, ownerId)) return unknown(saved)
  let result: Body
  try {
    result = asRecord(await transport.get(`/api/xcmax/local/employees/${encodeURIComponent(employeeId)}/runs?idempotency_key=${encodeURIComponent(saved.key)}`))
  } catch { return unknown(saved) }
  if (!unchanged(saved, scope, ownerId)) return unknown(saved)
  return acceptReceipt(storageKey, saved, result)
}

/** Reload/poll recovery uses only persisted original keys, never another POST. */
export async function readPendingAdminEmployeeReceipts(
  employeeId: string, transport: EmployeeRequestTransport, ownerId?: number | null,
): Promise<Body[]> {
  const scope = ownerScope(ownerId)
  if (!scope || !globalThis.crypto?.subtle) return []
  const binding = await requestScope(scope, currentServer(), productReadAccountEpoch.value, employeeId)
  if (!scopeCurrent(binding, ownerId)) return []
  const keys = Object.keys(localStorage).filter(key => key.startsWith(requestPrefix))
  const receipts: Body[] = []
  for (const storageKey of keys) {
    if (!scopeCurrent(binding, ownerId)) break
    let saved: StoredRequest
    try { saved = await loadRequest(storageKey, localStorage.getItem(storageKey) || '{}', binding, employeeId, ownerId) } catch { continue }
    if (saved.conflicted) continue
    receipts.push(await readReceipt(storageKey, saved, employeeId, binding, transport, ownerId))
  }
  return scopeCurrent(binding, ownerId) ? receipts : []
}

/** Persist only request identity and its joint binding. Sent operations only GET their original receipt. */
export async function executeAdminEmployee(
  employeeId: string, body: Body, transport: EmployeeRequestTransport, ownerId?: number | null,
): Promise<Body> {
  const scope = ownerScope(ownerId)
  if (!scope || !globalThis.crypto?.subtle || !crypto.randomUUID) throw new Error('登录身份尚未就绪，未提交员工任务。')
  const server = currentServer(), epoch = productReadAccountEpoch.value
  const identity = JSON.stringify(canonical([scope, employeeId, body]))
  const active = inFlight.get(identity)
  if (active) return active
  const operation = (async () => {
    const [digest, binding] = await Promise.all([sha256(identity), requestScope(scope, server, epoch, employeeId)])
    if (!scopeCurrent(binding, ownerId)) {
      throw new Error('账号或服务器已切换，未提交员工任务。')
    }
    const storageKey = requestPrefix + digest
    const prior = localStorage.getItem(storageKey)
    let saved: StoredRequest
    if (prior) {
      try { saved = await loadRequest(storageKey, prior, binding, employeeId, ownerId) } catch (error) {
        if (error instanceof RequestBindingMismatch) return unknown(error.identity)
        throw error
      }
      if (saved.conflicted) throw conflict()
    } else {
      saved = { version: 3, key: asString(body.idempotency_key || body.turn_id) || crypto.randomUUID(),
        bindingDigest: binding.bindingDigest }
      persistRequest(storageKey, saved)
    }
    if (!unchanged(saved, binding, ownerId)) return unknown(saved)
    const path = `/api/xcmax/local/employees/${encodeURIComponent(employeeId)}`
    if (prior) return readReceipt(storageKey, saved, employeeId, binding, transport, ownerId)
    try {
      const result = asRecord(await transport.post(`${path}/execute`, { ...body, idempotency_key: saved.key, turn_id: saved.key }))
      if (!unchanged(saved, binding, ownerId)) return unknown(saved)
      return acceptReceipt(storageKey, saved, result)
    } catch (error) {
      if (asRecord(error).status === 409) {
        saved.conflicted = true
        persistRequest(storageKey, saved)
        throw conflict()
      }
      if (!unchanged(saved, binding, ownerId)) return unknown(saved)
      return readReceipt(storageKey, saved, employeeId, binding, transport, ownerId)
    }
  })()
  inFlight.set(identity, operation)
  try { return await operation } finally { inFlight.delete(identity) }
}
