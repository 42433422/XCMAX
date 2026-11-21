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
type StoredRequest = { key: string; server: string; ownerScope: string; entryDigest: string; runId?: string; conflicted?: boolean }

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
function currentServer(): string { return getApiBase() || window.location.origin }
function unchanged(saved: StoredRequest, ownerId?: number | null): boolean {
  return saved.ownerScope === ownerScope(ownerId) && saved.server === currentServer()
}
function unknown(saved: StoredRequest): Body {
  return { success: false, execution_state: 'unknown', retryable: false, run_id: saved.runId || '',
    requires_reconciliation: true, idempotency_key: saved.key, turn_id: saved.key,
    message: '结果待核对，请在原账号和服务器读取任务回执，勿重复提交。' }
}
function conflict(): Error { return Object.assign(new Error('原请求标识与已有任务冲突，请核对原任务。'), { status: 409 }) }

async function digestText(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}

function restoreRequest(raw: string, scope: string, employeeId: string, entryDigest: string): StoredRequest {
  const previous = asRecord(JSON.parse(raw))
  if (!asString(previous.key) || !asString(previous.server) || previous.ownerScope !== scope
    || ('entryDigest' in previous ? previous.entryDigest !== entryDigest : previous.employeeId !== employeeId)
    || (previous.runId != null && typeof previous.runId !== 'string')) throw new Error('原员工请求身份缺失，请核对原任务。')
  // Rebuild the legacy record: only the current entry's digest is persisted.
  return { key: asString(previous.key), server: asString(previous.server), ownerScope: scope, entryDigest,
    ...(previous.runId ? { runId: asString(previous.runId) } : {}),
    ...(previous.conflicted ? { conflicted: true } : {}) }
}

function persistRequest(storageKey: string, saved: StoredRequest): void {
  const encoded = JSON.stringify(saved)
  if (localStorage.getItem(storageKey) !== encoded) localStorage.setItem(storageKey, encoded)
  if (localStorage.getItem(storageKey) !== encoded) throw new Error('无法保存员工请求身份，未提交任务。')
}

function acceptReceipt(storageKey: string, saved: StoredRequest, result: Body): Body {
  if (asString(result.idempotency_key || result.turn_id) !== saved.key || !asString(result.run_id)
    || (saved.runId && saved.runId !== asString(result.run_id))) return unknown(saved)
  if (!saved.runId) {
    saved.runId = asString(result.run_id)
    try { persistRequest(storageKey, saved) } catch { return unknown(saved) }
  }
  const state = adminEmployeeState(result)
  if (['completed', 'failed', 'cancelled', 'rejected'].includes(state)) {
    if (localStorage.getItem(storageKey) === JSON.stringify(saved)) localStorage.removeItem(storageKey)
  }
  return { ...result, execution_state: state, success: state === 'completed', retryable: false }
}

async function readReceipt(
  storageKey: string, saved: StoredRequest, employeeId: string, transport: EmployeeRequestTransport, ownerId?: number | null,
): Promise<Body> {
  const epoch = productReadAccountEpoch.value
  if (saved.conflicted || !unchanged(saved, ownerId)) return unknown(saved)
  let result: Body
  try {
    persistRequest(storageKey, saved)
    if (epoch !== productReadAccountEpoch.value || !unchanged(saved, ownerId)) return unknown(saved)
    result = asRecord(await transport.get(`/api/xcmax/local/employees/${encodeURIComponent(employeeId)}/runs?idempotency_key=${encodeURIComponent(saved.key)}`))
  } catch { return unknown(saved) }
  if (epoch !== productReadAccountEpoch.value || !unchanged(saved, ownerId)) return unknown(saved)
  return acceptReceipt(storageKey, saved, result)
}

/** Reload/poll recovery uses only persisted original keys, never another POST. */
export async function readPendingAdminEmployeeReceipts(
  employeeId: string, transport: EmployeeRequestTransport, ownerId?: number | null,
): Promise<Body[]> {
  const scope = ownerScope(ownerId)
  if (!scope) return []
  const server = currentServer(), epoch = productReadAccountEpoch.value
  const entryDigest = await digestText(employeeId)
  if (scope !== ownerScope(ownerId) || server !== currentServer() || epoch !== productReadAccountEpoch.value) return []
  const keys = Object.keys(localStorage).filter(key => key.startsWith(requestPrefix))
  const receipts: Body[] = []
  for (const storageKey of keys) {
    if (scope !== ownerScope(ownerId) || server !== currentServer() || epoch !== productReadAccountEpoch.value) break
    let saved: StoredRequest
    try { saved = restoreRequest(localStorage.getItem(storageKey) || '{}', scope, employeeId, entryDigest) } catch { continue }
    if (saved.conflicted) continue
    receipts.push(await readReceipt(storageKey, saved, employeeId, transport, ownerId))
  }
  return ownerScope(ownerId) === scope && server === currentServer() && epoch === productReadAccountEpoch.value ? receipts : []
}

/** Persist only identity/digests. A sent operation can only GET its original receipt. */
export async function executeAdminEmployee(
  employeeId: string, body: Body, transport: EmployeeRequestTransport, ownerId?: number | null,
): Promise<Body> {
  const scope = ownerScope(ownerId)
  if (!scope || !crypto?.subtle || !crypto.randomUUID) throw new Error('登录身份尚未就绪，未提交员工任务。')
  const server = currentServer(), epoch = productReadAccountEpoch.value
  const identity = JSON.stringify(canonical([scope, employeeId, body]))
  const active = inFlight.get(identity)
  if (active) return active
  const operation = (async () => {
    const [identityDigest, entryDigest] = await Promise.all([digestText(identity), digestText(employeeId)])
    if (scope !== ownerScope(ownerId) || server !== currentServer() || epoch !== productReadAccountEpoch.value) {
      throw new Error('账号或服务器已切换，未提交员工任务。')
    }
    const storageKey = requestPrefix + identityDigest
    const prior = localStorage.getItem(storageKey)
    let saved: StoredRequest
    if (prior) {
      saved = restoreRequest(prior, scope, employeeId, entryDigest)
      if (saved.conflicted) throw conflict()
    } else {
      saved = { key: asString(body.idempotency_key || body.turn_id) || crypto.randomUUID(), server, ownerScope: scope, entryDigest }
      persistRequest(storageKey, saved)
    }
    if (!unchanged(saved, ownerId) || epoch !== productReadAccountEpoch.value) return unknown(saved)
    const path = `/api/xcmax/local/employees/${encodeURIComponent(employeeId)}`
    if (prior) return readReceipt(storageKey, saved, employeeId, transport, ownerId)
    try {
      const result = asRecord(await transport.post(`${path}/execute`, { ...body, idempotency_key: saved.key, turn_id: saved.key }))
      if (epoch !== productReadAccountEpoch.value || !unchanged(saved, ownerId)) return unknown(saved)
      return acceptReceipt(storageKey, saved, result)
    } catch (error) {
      if (asRecord(error).status === 409) {
        saved.conflicted = true
        persistRequest(storageKey, saved)
        throw conflict()
      }
      if (epoch !== productReadAccountEpoch.value || !unchanged(saved, ownerId)) return unknown(saved)
      return readReceipt(storageKey, saved, employeeId, transport, ownerId)
    }
  })()
  inFlight.set(identity, operation)
  try { return await operation } finally { inFlight.delete(identity) }
}
