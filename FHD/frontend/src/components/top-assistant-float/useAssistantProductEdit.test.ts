import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { webcrypto } from 'node:crypto'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'

const api = vi.hoisted(() => ({ update: vi.fn(), product: vi.fn(), run: vi.fn(), proceed: vi.fn() }))
vi.mock('@/api/products', () => ({ default: { updateProduct: api.update, getProduct: api.product } }))
vi.mock('@/api/agentRuns', () => ({ default: { getRun: api.run, continueRun: api.proceed } }))
const mods = reactive({ activeModId: 'mod-a' })
vi.mock('@/stores/mods', () => ({ useModsStore: () => mods }))
import { useAssistantProductEdit } from './useAssistantProductEdit'

const product = { id: 11, name: '私人示例名称', model_number: 'SYN-11', price: 12.5, unit: '件' }
function scope(user = 7) {
  const value = { tenantId: 5, localUserId: user }
  setRuntimeTenantStorageScopeInput(value)
  updateProductReadAccountScope(value)
}
function run(status = 'waiting_user', output: Record<string, unknown> = {}) {
  const receipt = status === 'completed' ? { ...output, business_action_id: 'action_1' } : output
  return { run_id: 'run_original', user_id: '7', message: '', status, metadata: { runtime_context: { tenant_id: 5, mod_id: 'mod-a' } }, steps: [{ step_id: 'step_1', node_id: 'products_update_compat', tool_id: 'products', action: 'update', params: product, status: status === 'completed' ? 'completed' : 'waiting_user', output: receipt }], tool_calls: status === 'completed' ? [{ call_id: 'call_1', step_id: 'step_1', node_id: 'products_update_compat', tool_id: 'products', action: 'update', params: product, status: 'completed', output: receipt }] : [] }
}
function approval() {
  return { grant: 'synthetic-approval', run_id: 'run_original', step_id: 'step_1', tool_id: 'products', action: 'update' }
}

describe('product edit receipts', () => {
  beforeEach(() => {
    localStorage.clear(); vi.clearAllMocks(); mods.activeModId = 'mod-a'; scope()
    vi.stubGlobal('crypto', webcrypto)
    const held = new Set<string>()
    Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (key: string, _opts: unknown, fn: (lock: object | null) => Promise<unknown>) => {
      if (held.has(key)) return fn(null)
      held.add(key)
      try { return await fn({}) } finally { held.delete(key) }
    } } })
    api.update.mockResolvedValue({ success: false, pending_approval: true, run_id: 'run_original', agent_status: 'waiting_user' })
  })

  it('retains a hash-only original and needs an explicit approval plus independent readback', async () => {
    const onVerified = vi.fn(), edit = useAssistantProductEdit(onVerified)
    await edit.saveProductRow(product)
    expect(api.update).toHaveBeenCalledOnce()
    expect(edit.statusFor(product.id)?.state).toBe('pending')
    const key = Object.keys(localStorage).find(k => k.startsWith('xcagi-product-edit-receipt-v1:'))!
    const saved = localStorage.getItem(key)!
    expect(saved).not.toContain(product.name)
    expect(saved).not.toContain(product.model_number)
    expect(JSON.parse(saved)).toMatchObject({ productId: 11, runId: 'run_original', approvalSent: false, requestDigest: expect.stringMatching(/^[0-9a-f]{64}$/) })
    await edit.saveProductRow(product)
    expect(api.update).toHaveBeenCalledOnce()
    api.run.mockResolvedValue({ success: true, data: run(), approval: approval() })
    await edit.checkProductRow(product)
    expect(edit.statusFor(11)?.canApprove).toBe(true)
    expect(api.proceed).not.toHaveBeenCalled()
    api.proceed.mockResolvedValue({ success: true, data: run('queued') })
    await edit.checkProductRow(product, true)
    expect(api.proceed).toHaveBeenCalledOnce()
    await edit.checkProductRow(product, true)
    expect(api.proceed).toHaveBeenCalledOnce()
    expect(onVerified).not.toHaveBeenCalled()
    api.run.mockResolvedValue({ success: true, data: run('completed', { success: true, business_verification: { verified: true } }) })
    api.product.mockResolvedValue({ success: true, data: product })
    await edit.checkProductRow(product)
    expect(edit.statusFor(11)?.state).toBe('verified')
    expect(api.product).toHaveBeenCalledWith(11)
    expect(localStorage.getItem(key)).toBeNull()
    expect(onVerified).toHaveBeenCalledWith(11)
  })

  it.each(['lost', 'no-id'])('never reissues an original request after %s', async kind => {
    const edit = useAssistantProductEdit(vi.fn())
    if (kind === 'lost') api.update.mockRejectedValueOnce(new Error('connection lost'))
    else api.update.mockResolvedValueOnce({ success: true })
    if (kind === 'lost') await expect(edit.saveProductRow(product)).rejects.toThrow()
    else await edit.saveProductRow(product)
    const reloaded = useAssistantProductEdit(vi.fn())
    expect(reloaded.statusFor(11)?.state).toBe('unknown')
    await reloaded.saveProductRow(product)
    await reloaded.checkProductRow(product)
    expect(api.update).toHaveBeenCalledOnce()
    expect(api.proceed).not.toHaveBeenCalled()
    expect(api.product).not.toHaveBeenCalled()
  })

  it.each(['wrong-owner', 'wrong-tenant', 'wrong-mod', 'wrong-params', 'bad-receipt', 'unknown-receipt', 'missing-call', 'changed-product'])('keeps %s unknown', async kind => {
    const edit = useAssistantProductEdit(vi.fn())
    await edit.saveProductRow(product)
    const original = run('completed', { success: true, business_verification: { verified: true } })
    if (kind === 'wrong-owner') original.user_id = '8'
    if (kind === 'wrong-tenant') original.metadata.runtime_context.tenant_id = 8
    if (kind === 'wrong-mod') original.metadata.runtime_context.mod_id = 'other'
    if (kind === 'wrong-params') original.steps[0].params = { ...product, price: 20 }
    if (kind === 'bad-receipt') original.steps[0].output = { success: true }
    if (kind === 'unknown-receipt') original.steps[0].output = { success: true, outcome: 'unknown', business_verification: { verified: true } }
    if (kind === 'missing-call') original.tool_calls = []
    api.run.mockResolvedValue({ success: true, data: original })
    api.product.mockResolvedValue({ success: true, data: kind === 'changed-product' ? { ...product, price: 99 } : product })
    await edit.checkProductRow(product)
    expect(edit.statusFor(11)?.state).toBe('unknown')
    await edit.saveProductRow(product)
    expect(api.update).toHaveBeenCalledOnce()
  })

  it('does not attach a late original response across account changes', async () => {
    let resolve!: (value: unknown) => void
    api.update.mockImplementationOnce(() => new Promise(r => { resolve = r }))
    const edit = useAssistantProductEdit(vi.fn())
    const saving = edit.saveProductRow(product)
    await vi.waitFor(() => expect(api.update).toHaveBeenCalledOnce())
    scope(8)
    resolve({ success: true, run_id: 'run_original' })
    await saving
    expect(edit.statusFor(11)).toBeUndefined()
    scope(7)
    expect(edit.statusFor(11)?.state).toBe('unknown')
    await edit.saveProductRow(product)
    expect(api.update).toHaveBeenCalledOnce()
  })

  it('discards a delayed run lookup even if the active Mod switches away and back', async () => {
    const edit = useAssistantProductEdit(vi.fn())
    await edit.saveProductRow(product)
    let resolve!: (value: unknown) => void
    api.run.mockImplementationOnce(() => new Promise(r => { resolve = r }))
    const checking = edit.checkProductRow(product)
    await vi.waitFor(() => expect(api.run).toHaveBeenCalledOnce())
    mods.activeModId = 'mod-b'
    mods.activeModId = 'mod-a'
    resolve({ success: true, data: run('completed', { success: true, business_verification: { verified: true } }) })
    await checking
    expect(api.product).not.toHaveBeenCalled()
    expect(edit.statusFor(11)?.state).toBe('unknown')
  })

  it('does not accept a conflicting unknown outcome inside the tool receipt', async () => {
    const edit = useAssistantProductEdit(vi.fn())
    await edit.saveProductRow(product)
    const original = run('completed', { success: true, business_verification: { verified: true } })
    original.tool_calls[0].output = { success: true, business_action_id: 'action_1', business_verification: { verified: true, execution_outcome: 'unknown' } }
    api.run.mockResolvedValue({ success: true, data: original })
    await edit.checkProductRow(product)
    expect(api.product).not.toHaveBeenCalled()
    expect(edit.statusFor(11)?.state).toBe('unknown')
  })

  it.each(['action', 'params', 'node'])('rejects a tool receipt with mismatched %s', async kind => {
    const edit = useAssistantProductEdit(vi.fn())
    await edit.saveProductRow(product)
    const original = run('completed', { success: true, business_verification: { verified: true } })
    if (kind === 'action') original.tool_calls[0].output = { ...original.tool_calls[0].output, business_action_id: 'other' }
    if (kind === 'params') original.tool_calls[0].params = { ...product, price: 99 }
    if (kind === 'node') original.tool_calls[0].node_id = 'other'
    api.run.mockResolvedValue({ success: true, data: original })
    await edit.checkProductRow(product)
    expect(api.product).not.toHaveBeenCalled()
    expect(edit.statusFor(11)?.state).toBe('unknown')
  })

  it('does not dispatch without a selected Mod', async () => {
    mods.activeModId = ''
    const edit = useAssistantProductEdit(vi.fn())
    await edit.saveProductRow(product)
    expect(api.update).not.toHaveBeenCalled()
  })

  it('refuses dispatch when durable storage or cross-window locking is unavailable', async () => {
    Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined })
    const edit = useAssistantProductEdit(vi.fn())
    await expect(edit.saveProductRow(product)).rejects.toThrow(/跨窗口保护/)
    expect(api.update).not.toHaveBeenCalled()
  })

  it('does not dispatch if durable receipt storage fails', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('quota') })
    const edit = useAssistantProductEdit(vi.fn())
    await expect(edit.saveProductRow(product)).rejects.toThrow('quota')
    expect(api.update).not.toHaveBeenCalled()
    vi.restoreAllMocks()
  })

  it('serializes concurrent submissions for the same owner and product', async () => {
    let finish!: (response: unknown) => void
    api.update.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const first = useAssistantProductEdit(vi.fn()), second = useAssistantProductEdit(vi.fn())
    const pending = first.saveProductRow(product)
    await vi.waitFor(() => expect(api.update).toHaveBeenCalledOnce())
    await expect(second.saveProductRow(product)).rejects.toThrow(/正在处理中/)
    finish({ success: false, pending_approval: true, run_id: 'run_original', agent_status: 'waiting_user' })
    await pending
    await second.saveProductRow(product)
    expect(api.update).toHaveBeenCalledOnce()
  })

  it('never reuses an approval after a lost approval response', async () => {
    const edit = useAssistantProductEdit(vi.fn())
    await edit.saveProductRow(product)
    api.run.mockResolvedValue({ success: true, data: run(), approval: approval() })
    api.proceed.mockRejectedValueOnce(new Error('response lost'))
    await edit.checkProductRow(product, true)
    expect(api.proceed).toHaveBeenCalledOnce()
    await edit.checkProductRow(product, true)
    expect(api.proceed).toHaveBeenCalledOnce()
    expect(edit.statusFor(11)?.state).toBe('pending')
    expect(edit.statusFor(11)?.canApprove).toBe(false)
  })

  it.each(['call', 'step-output', 'final-output', 'verification', 'recovery'])('does not approve a stale waiting task with %s execution evidence', async kind => {
    const edit = useAssistantProductEdit(vi.fn())
    await edit.saveProductRow(product)
    const original = run() as ReturnType<typeof run> & { final_output?: Record<string, unknown> }
    if (kind === 'call') original.tool_calls = run('completed').tool_calls
    if (kind === 'step-output') original.steps[0].output = { success: true }
    if (kind === 'final-output') original.final_output = { execution_outcome: 'unknown' }
    if (kind === 'verification') original.final_output = { business_verification: { requires_reconciliation: true } }
    if (kind === 'recovery') Object.assign(original.metadata, { recovery: { requires_reconciliation: true } })
    api.run.mockResolvedValue({ success: true, data: original, approval: approval() })
    await edit.checkProductRow(product, true)
    await edit.checkProductRow(product, true)
    expect(api.proceed).not.toHaveBeenCalled()
    expect(api.product).not.toHaveBeenCalled()
    expect(edit.statusFor(11)?.canApprove).toBe(false)
    await edit.saveProductRow(product)
    expect(api.update).toHaveBeenCalledOnce()
  })
})
