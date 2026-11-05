import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useChatOrchestrationPrintFlow } from './useChatOrchestrationPrintFlow'
import { useOnboardingFirstOrderRun } from '../useOnboardingFirstOrderRun'
import type { ChatLocalScope } from './chatOrchestrationShared'

const { audit, dispatch, createRun, bindRun } = vi.hoisted(() => ({ audit: vi.fn(), dispatch: vi.fn(), createRun: vi.fn(), bindRun: vi.fn(() => true) }))
vi.mock('@/utils/shipmentMgmtPostPrint', () => ({ fetchShipmentRecordsForUnit: audit, summarizeShipmentRecordsForAudit: () => ({ headline: 'audit', detailLines: ['audit'] }) }))
vi.mock('@/workflow/coreWorkflowDispatcher', () => ({ dispatchCoreWorkflowModRun: dispatch }))
vi.mock('@/constants/coreWorkflowMod', () => ({ isCoreWorkflowModInstalled: () => false }))
vi.mock('@/api/agentRuns', () => ({ default: { createRun } }))
vi.mock('@/constants/productFlow', () => ({ bindPendingFirstAiTaskRun: bindRun, isFirstAiTaskPending: () => true }))

function deferred<T>() {
  let resolve!: (value: T) => void
  return { promise: new Promise<T>(done => { resolve = done }), resolve: (value: T) => resolve(value) }
}
function ownership() {
  let current = true, owner = true
  const scope: ChatLocalScope = { sessionId: 'original', isCurrent: () => current && owner, isOwnerCurrent: () => owner }
  return { scope, leave: () => { current = false }, changeOwner: () => { owner = false } }
}
function printFixture(scope: ChatLocalScope) {
  const deps = {
    captureLocalScope: () => scope,
    saveMessage: vi.fn().mockResolvedValue(undefined), addAndSaveMessage: vi.fn().mockResolvedValue(undefined),
    modsStore: { modsForUi: [] }, taskList: ref([]), createTaskId: () => 'original-print', upsertTask: vi.fn(),
    getLastAiMessageRef: vi.fn(() => 'original-message'), emitAssistantPush: vi.fn(), readWorkflowEmployeeEnabledMap: () => ({ shipment_mgmt: true }), upsertWorkflowEmployeeTask: vi.fn(),
    lastShipmentExecution: ref({ filePath: 'synthetic.xlsx', labelPaths: [], purchaseUnit: 'synthetic', orderId: 1 }),
    executePrintTask: vi.fn(), buildPrintSummaryMessage: () => '打印已提交，不能撤销已提交的打印',
  }
  return { deps, api: useChatOrchestrationPrintFlow(deps as unknown as Parameters<typeof useChatOrchestrationPrintFlow>[0]) }
}

describe('local physical-action receipts retain original ownership', () => {
  it.each(['stop', 'session', 'owner'])('does not attach a print result to a newer view after %s', async change => {
    vi.clearAllMocks()
    const own = ownership(), { deps, api } = printFixture(own.scope), pending = deferred<{ success: boolean }>()
    deps.executePrintTask.mockReturnValueOnce(pending.promise)
    const printing = api.handleStartPrintCommand('开始打印')
    expect(deps.executePrintTask).toHaveBeenCalledOnce()
    deps.upsertTask.mockClear()
    if (change === 'owner') own.changeOwner(); else own.leave()
    pending.resolve({ success: true })
    await printing
    expect(deps.addAndSaveMessage).not.toHaveBeenCalled()
    expect(deps.upsertTask).not.toHaveBeenCalled()
    expect(audit).not.toHaveBeenCalled()
    expect(deps.saveMessage.mock.calls).toEqual(change === 'owner' ? [] : [['ai', expect.stringContaining('打印已提交'), 'original']])
  })

  it('keeps the print receipt message reference while its save is pending', async () => {
    vi.clearAllMocks()
    const own = ownership(), { deps, api } = printFixture(own.scope), saved = deferred<void>()
    deps.getLastAiMessageRef.mockReturnValue('receipt')
    deps.executePrintTask.mockResolvedValue({ success: false })
    deps.addAndSaveMessage.mockReturnValueOnce(saved.promise)
    const printing = api.handleStartPrintCommand('开始打印')
    await vi.waitFor(() => expect(deps.addAndSaveMessage).toHaveBeenCalledOnce())
    deps.getLastAiMessageRef.mockReturnValue('unrelated-later-message')
    saved.resolve(); await printing
    expect(deps.upsertTask).toHaveBeenLastCalledWith(expect.objectContaining({ messageRef: 'receipt' }))
  })

  it('stops delayed post-print audit before dispatch or UI writes after a session change', async () => {
    vi.clearAllMocks()
    const own = ownership(), { deps, api } = printFixture(own.scope), pending = deferred<unknown[]>()
    deps.executePrintTask.mockResolvedValue({ success: true })
    audit.mockReturnValueOnce(pending.promise)
    const printing = api.handleStartPrintCommand('开始打印')
    await vi.waitFor(() => expect(audit).toHaveBeenCalledOnce())
    expect(deps.addAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('打印已提交'), 'ai', undefined, 'original')
    deps.upsertTask.mockClear(); own.leave(); pending.resolve([])
    await printing
    expect(dispatch).not.toHaveBeenCalled()
    expect(deps.upsertTask).not.toHaveBeenCalled()
    expect(deps.addAndSaveMessage).toHaveBeenCalledOnce()
  })

  it.each(['saving', 'creating', 'owner'])('fences onboarding work while %s is pending', async phase => {
    vi.clearAllMocks()
    const own = ownership(), pending = deferred<unknown>()
    const options = { sessionId: () => 'original', saveMessage: vi.fn().mockResolvedValue(undefined), addAndSaveMessage: vi.fn(), refreshTasks: vi.fn() }
    if (phase === 'saving') options.saveMessage.mockReturnValueOnce(pending.promise)
    else createRun.mockReturnValueOnce(pending.promise)
    const starting = useOnboardingFirstOrderRun(options).tryStart('新手第一单 演示出货单', own.scope)
    if (phase !== 'saving') await vi.waitFor(() => expect(createRun).toHaveBeenCalledOnce())
    if (phase === 'owner') own.changeOwner(); else own.leave()
    pending.resolve({ data: { run_id: 'original-run' } })
    await starting
    if (phase === 'saving') expect(createRun).not.toHaveBeenCalled()
    expect(bindRun).not.toHaveBeenCalled()
    expect(options.addAndSaveMessage).not.toHaveBeenCalled()
    expect(options.refreshTasks).not.toHaveBeenCalled()
    expect(options.saveMessage.mock.calls.length).toBe(phase === 'creating' ? 2 : 1)
    if (phase === 'creating') expect(options.saveMessage).toHaveBeenLastCalledWith('ai', expect.stringContaining('original-run'), 'original')
  })
})
