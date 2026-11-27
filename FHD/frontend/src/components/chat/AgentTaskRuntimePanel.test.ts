import { createHash } from 'node:crypto'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AgentTaskRuntimePanel from './AgentTaskRuntimePanel.vue'
import agentRunsApi from '@/api/agentRuns'
import { downloadBlob } from '@/utils'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { writeActiveExtensionModIdToStorage } from '@/utils/xcagiStorageKeys'
import type { AgentRunResponse, AgentTaskSummary, AgentVerificationReport, AgentVerificationStatus } from '@/api/agentRuns'
import { taskSummariesToTaskItems } from '@/utils/agentTaskWorkspaceModel'

vi.mock('@/utils', () => ({ downloadBlob: vi.fn() }))

const task = {
  id: 'agent_task_task-1',
  type: 'agent_task',
  title: '月度库存核对',
  source: 'agent' as const,
  status: 'running' as const,
  startedAt: 1,
  updatedAt: 2,
  payload: {
    runCount: 2,
    attempt: 2,
    workspaceId: 'inventory-workspace',
    workspaceIsolation: 'business_workspace',
    artifactCount: 1,
    steps: [{ step_id: 'step-1', tool_id: 'business_db', action: 'read', status: 'running' }],
    toolCalls: [{ call_id: 'call-1', tool_id: 'business_db', action: 'read', status: 'running' }],
  },
}

describe('AgentTaskRuntimePanel', () => {
  afterEach(() => vi.restoreAllMocks())

  function artifactResponse(content: string): Response {
    return new Response(content, { headers: {
      'X-Artifact-SHA256': createHash('sha256').update(content).digest('hex'),
      'X-Artifact-Size': String(content.length),
    } })
  }

  const mountTask = (overrides: Record<string, unknown> = {}) =>
    mount(AgentTaskRuntimePanel, {
      props: { task: { ...task, ...overrides } },
      global: { mocks: { $t: (key: string) => key } },
    })

  function verificationTask(status: AgentVerificationStatus = 'inconclusive') {
    const report: AgentVerificationReport = {
      protocol: 'xcagi.result-verification.v1',
      status,
      accepted: ['verified', 'not_required'].includes(status),
      independently_verified_steps: status === 'verified' ? 1 : 0,
      contract_only_steps: 1,
      steps: [{ call_id: 'call-1', contract_sha256: 'contract', status, checks: [{ code: 'persisted_effect', passed: status === 'verified' }] }],
    }
    return {
      ...task,
      status: 'blocked' as const,
      payload: { activeRunId: 'run-1', rawRunStatus: 'blocked', finalOutput: { verification: report } },
    }
  }

  it('downloads an owned artifact and retains a retry action after failure', async () => {
    const content = 'spreadsheet'
    const download = vi
      .spyOn(agentRunsApi, 'downloadArtifact')
      .mockRejectedValueOnce(new Error('expired session'))
      .mockResolvedValueOnce(artifactResponse(content))
    const wrapper = mountTask({
      status: 'success',
      payload: {
        activeRunId: 'run-1',
        artifacts: [
          { artifact_id: 'xlsx-1', artifact_type: 'file', name: '销售报表.xlsx', uri: '/api/agent/runs/run-1/artifacts/xlsx-1' },
          { artifact_id: 'foreign', artifact_type: 'file', name: 'foreign.xlsx', uri: '/api/agent/runs/other/artifacts/foreign' },
        ],
      },
    })
    const button = wrapper.get('.agent-artifact-downloads button')
    expect(wrapper.findAll('.agent-artifact-downloads button')).toHaveLength(1)
    await button.trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('下载失败')
    expect(downloadBlob).not.toHaveBeenCalled()
    await button.trigger('click')
    await vi.waitFor(() => expect(downloadBlob).toHaveBeenCalledOnce())
    expect(download).toHaveBeenLastCalledWith('run-1', 'xlsx-1')
    expect(vi.mocked(downloadBlob).mock.calls[0]?.[0].size).toBe(content.length)
    expect(vi.mocked(downloadBlob).mock.calls[0]?.[1]).toBe('销售报表.xlsx')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    download.mockRestore()
  })

  it.each(['run', 'task', 'account', 'session', 'mod', 'unmount'])('does not deliver old artifact bytes after the %s changes', async change => {
    vi.mocked(downloadBlob).mockClear()
    const content = 'isolated business evidence'
    let finish!: (bytes: ArrayBuffer) => void
    const bytes = new Promise<ArrayBuffer>(resolve => { finish = resolve })
    const reply = artifactResponse(content)
    const readBytes = vi.spyOn(reply, 'arrayBuffer').mockReturnValue(bytes)
    vi.spyOn(agentRunsApi, 'downloadArtifact').mockResolvedValue(reply)
    const source = { ...task, payload: { activeRunId: 'run-1', artifacts: [
      { artifact_id: 'xlsx-1', artifact_type: 'file', name: '隔离验收报表.xlsx', uri: '/api/agent/runs/run-1/artifacts/xlsx-1' },
    ] } }
    const wrapper = mountTask(source)
    await wrapper.get('.agent-artifact-downloads button').trigger('click'); await flushPromises()
    expect(readBytes).toHaveBeenCalledOnce()
    if (change === 'run') await wrapper.setProps({ task: { ...source, payload: { ...source.payload, activeRunId: 'run-2' } } })
    if (change === 'task') await wrapper.setProps({ task: { ...source, id: 'agent_task_task-2' } })
    if (change === 'account') productReadAccountEpoch.value++
    if (change === 'session') invalidateEnterpriseSessionCache()
    if (change === 'mod') writeActiveExtensionModIdToStorage('other-customer-mod')
    if (change === 'unmount') wrapper.unmount()
    finish(new TextEncoder().encode(content).buffer)
    await flushPromises()
    expect(downloadBlob).not.toHaveBeenCalled()
    if (change !== 'unmount') wrapper.unmount()
    if (change === 'mod') writeActiveExtensionModIdToStorage(null)
  })

  it('keeps a legitimate artifact download when only the same run status advances', async () => {
    vi.mocked(downloadBlob).mockClear()
    const content = 'isolated business evidence'
    let finish!: (bytes: ArrayBuffer) => void
    const reply = artifactResponse(content)
    vi.spyOn(reply, 'arrayBuffer').mockReturnValue(new Promise(resolve => { finish = resolve }))
    vi.spyOn(agentRunsApi, 'downloadArtifact').mockResolvedValue(reply)
    const source = { ...task, payload: { activeRunId: 'run-1', rawRunStatus: 'running', artifacts: [
      { artifact_id: 'xlsx-1', artifact_type: 'file', name: '隔离验收报表.xlsx', uri: '/api/agent/runs/run-1/artifacts/xlsx-1' },
    ] } }
    const wrapper = mountTask(source)
    await wrapper.get('.agent-artifact-downloads button').trigger('click'); await flushPromises()
    await wrapper.setProps({ task: { ...source, payload: { ...source.payload, rawRunStatus: 'completed' } } })
    finish(new TextEncoder().encode(content).buffer)
    await vi.waitFor(() => expect(downloadBlob).toHaveBeenCalledOnce())
    expect(vi.mocked(downloadBlob).mock.calls[0]?.[0].size).toBe(content.length)
    expect(vi.mocked(downloadBlob).mock.calls[0]?.[1]).toBe('隔离验收报表.xlsx')
    wrapper.unmount()
  })

  it('shows traceable runtime details and controls the exact task', async () => {
    const wrapper = mountTask()

    expect(wrapper.text()).toContain('inventory-workspace')
    expect(wrapper.text()).toContain('business_db.read')
    expect(wrapper.text()).toContain('chat.toolSessions')

    const buttons = wrapper.findAll('button')
    await buttons.find((button) => button.text() === 'chat.openTask')!.trigger('click')
    await buttons.find((button) => button.text() === 'chat.pauseTask')!.trigger('click')
    await buttons.find((button) => button.text() === 'chat.cancel')!.trigger('click')
    expect(wrapper.emitted('open')).toHaveLength(1)
    expect(wrapper.emitted('pause')).toHaveLength(1)
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('keeps an empty completed task compact and uses counter defaults', () => {
    const wrapper = mountTask({ status: 'success', payload: {} })

    expect(wrapper.find('.agent-task-workspace').exists()).toBe(false)
    expect(wrapper.find('.agent-task-steps').exists()).toBe(false)
    expect(wrapper.find('.agent-tool-sessions').exists()).toBe(false)
    expect(wrapper.find('.agent-task-evidence').text()).toContain('结果证据：0 条事件')
    expect(wrapper.findAll('button').map((button) => button.text())).toEqual(['chat.openTask'])
  })

  it('renders payload fallbacks, every step label, durations, and paused controls', async () => {
    const wrapper = mountTask({
      status: 'paused',
      payload: {
        runCount: 0,
        attempt: 0,
        workspacePath: '/tmp/task-worktree',
        steps: [
          { step_id: 'pending', tool_id: 'repo', action: 'inspect' },
          { step_id: 'running', description: '执行工具', status: 'running' },
          { step_id: 'retrying', description: '重试工具', status: 'retrying' },
          { step_id: 'waiting', description: '等待确认', status: 'waiting_user' },
          { step_id: 'completed', description: '完成工具', status: 'completed' },
          { step_id: 'failed', description: '失败工具', status: 'failed' },
          { step_id: 'skipped', description: '跳过工具', status: 'skipped' },
          { step_id: 'unknown', description: '未知状态', status: 'unknown' },
        ],
        toolCalls: [
          {
            call_id: 'timed',
            tool_id: 'terminal',
            action: 'test',
            status: 'completed',
            duration_ms: 42,
          },
        ],
        artifactCount: 0,
      },
    })

    expect(wrapper.text()).toContain('/tmp/task-worktree')
    expect(wrapper.text()).toContain('business_workspace')
    expect(wrapper.text()).toContain('repo.inspect')
    expect(wrapper.text()).toContain('待执行')
    expect(wrapper.text()).toContain('重试中')
    expect(wrapper.text()).toContain('等待确认')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('失败')
    expect(wrapper.text()).toContain('已跳过')
    expect(wrapper.text()).toContain('42ms')

    const buttons = wrapper.findAll('button')
    await buttons.find((button) => button.text() === 'chat.resumeTask')!.trigger('click')
    await buttons.find((button) => button.text() === 'chat.cancel')!.trigger('click')
    expect(wrapper.emitted('resume')).toHaveLength(1)
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it.each(['failed', 'cancelled', 'blocked'] as const)('offers a retry for %s tasks', async (status) => {
    const wrapper = mountTask({ status, payload: null })
    const retry = wrapper.findAll('button').find((button) => button.text() === 'chat.retryTask')

    expect(retry).toBeDefined()
    await retry!.trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
    expect(wrapper.findAll('button').some((button) => button.text() === 'chat.cancel')).toBe(status === 'blocked')
  })

  it('offers a real approval action only at the waiting checkpoint', async () => {
    const wrapper = mountTask({
      status: 'blocked',
      payload: {
        rawRunStatus: 'waiting_user',
        capabilities: { approve: true, pause: true, cancel: true },
      },
    })
    const approval = wrapper.findAll('button').find((button) => button.text() === '审批并执行')

    expect(approval).toBeDefined()
    await approval!.trigger('click')
    expect(wrapper.emitted('approve')).toHaveLength(1)
  })

  it('exposes persisted result output and artifact identity as evidence', () => {
    const wrapper = mountTask({
      status: 'success',
      payload: {
        eventCount: 8,
        completedToolCount: 1,
        artifactCount: 1,
        finalOutput: { node_outputs: { shipment: { success: true, order_id: 41 } } },
        artifacts: [{ artifact_id: 'art-1', name: 'shipment-41.docx', uri: '/tmp/shipment-41.docx' }],
      },
    })

    expect(wrapper.text()).toContain('8 条事件')
    expect(wrapper.text()).toContain('shipment-41.docx')
    expect(wrapper.find('.agent-result-evidence pre').text()).toContain('"order_id": 41')
  })

  it('shows a beginner-readable business result before optional technical JSON', () => {
    const wrapper = mountTask({
      status: 'success',
      payload: {
        eventCount: 4,
        completedToolCount: 1,
        finalOutput: {
          chat_payload: { success: true, response: '当前客户库暂无数据。' },
          node_outputs: { customers: { success: true, data: [] } },
        },
      },
    })

    expect(wrapper.find('.agent-result-summary').text()).toContain('业务结果')
    expect(wrapper.find('.agent-result-summary').text()).toContain('当前客户库暂无数据。')
    expect(wrapper.find('.agent-result-evidence summary').text()).toBe('技术明细（高级）')
    expect(wrapper.find('.agent-result-evidence').attributes('open')).toBeUndefined()
  })

  it('renders the canonical Business Harness summary and facts before raw node output', () => {
    const wrapper = mountTask({
      status: 'success',
      payload: {
        finalOutput: {
          business_result: {
            status: 'completed',
            summary: '订单创建成功',
            facts: { order_id: 41, order_number: 'SO-0041' },
          },
          node_outputs: { order: { message: '内部节点文本' } },
        },
      },
    })

    const summary = wrapper.find('.agent-result-summary').text()
    expect(summary).toContain('订单创建成功')
    expect(summary).toContain('订单 ID：41')
    expect(summary).toContain('业务单号：SO-0041')
    expect(summary).not.toContain('内部节点文本')
  })

  it.each([
    ['verified', '独立核验通过'],
    ['failed', '核验未通过'],
    ['inconclusive', '结果待核验，证据暂不可确认'],
    ['pending', '等待核验'],
    ['not_required', '已完成输出契约检查，无需独立读回'],
    ['not_verified', '尚无独立核验证据'],
  ] as const)('explains %s verification separately from execution and keeps checks in advanced details', (status, label) => {
    const wrapper = mountTask(verificationTask(status))
    const report = wrapper.get('.agent-result-verification')
    expect(report.text()).toContain('独立结果核验')
    expect(report.text()).toContain(label)
    expect(report.text()).toContain(`独立通过 ${status === 'verified' ? 1 : 0} 步 · 仅契约检查 1 步`)
    expect(report.text()).not.toContain('persisted_effect')
    expect(wrapper.get('.agent-verification-details').text()).toContain('persisted_effect')
    expect(wrapper.get('.agent-result-evidence').attributes('open')).toBeUndefined()
  })

  it('does not present an unverified successful receipt as a successful business result', () => {
    const source = verificationTask('failed')
    const wrapper = mountTask({
      ...source,
      payload: { ...source.payload, finalOutput: { ...source.payload.finalOutput, business_result: { summary: '订单创建成功' } } },
    })
    expect(wrapper.get('.agent-result-summary').text()).toContain('结果尚未完成核验')
    expect(wrapper.get('.agent-result-summary').text()).not.toContain('订单创建成功')
    expect(wrapper.get('.agent-result-summary').classes()).toContain('agent-result-summary--unverified')
  })

  it('keeps a metadata-only uncertain task summary pending reconciliation in the runtime panel', () => {
    const [projected] = taskSummariesToTaskItems([{
      task_id: 'task-unknown',
      status: 'completed',
      active_run_id: 'run-unknown',
      metadata: { reconciliation_required: true, business_result: { summary: '订单创建成功' } },
    } as AgentTaskSummary])
    const wrapper = mountTask(projected)

    expect(projected.payload?.rawRunStatus).toBe('unknown')
    expect(wrapper.get('.agent-result-summary').text()).toContain('结果待核对')
    expect(wrapper.get('.agent-result-summary').text()).not.toContain('订单创建成功')
    expect(wrapper.get('.agent-result-summary').classes()).toContain('agent-result-summary--unverified')
    expect(wrapper.find('.agent-verification-action').exists()).toBe(false)
  })

  it('does not use an older accepted verification to certify a currently uncertain run', () => {
    const source = verificationTask('verified')
    const wrapper = mountTask({
      ...source,
      payload: {
        ...source.payload,
        rawRunStatus: 'unknown',
        finalOutput: { ...source.payload.finalOutput, business_result: { summary: '订单创建成功' } },
      },
    })

    expect(wrapper.get('.agent-result-verification').attributes('data-status')).toBe('inconclusive')
    expect(wrapper.get('.agent-result-summary').text()).toContain('结果待核对')
    expect(wrapper.get('.agent-result-summary').text()).not.toContain('订单创建成功')
    expect(wrapper.find('.agent-verification-action').exists()).toBe(false)
  })

  it.each(['failed', 'inconclusive', 'pending', 'not_verified'] as const)(
    'does not certify a contradictory accepted %s report', (status) => {
      const source = verificationTask(status)
      source.payload.finalOutput.verification.accepted = true
      const wrapper = mountTask({
        ...source,
        payload: { ...source.payload, finalOutput: { ...source.payload.finalOutput, business_result: { summary: '订单创建成功' } } },
      })

      expect(wrapper.get('.agent-result-summary').text()).toContain('结果尚未完成核验')
      expect(wrapper.get('.agent-result-summary').text()).not.toContain('订单创建成功')
      expect(wrapper.get('.agent-result-summary').classes()).toContain('agent-result-summary--unverified')
    },
  )

  it('does not claim a saved receipt while execution has only frozen a pending contract', () => {
    const source = verificationTask('pending')
    source.payload.finalOutput.verification.steps = [{ call_id: 'call-1', status: 'pending', code: 'awaiting_execution_receipt', checks: [] }]
    const wrapper = mountTask({ ...source, status: 'running', payload: { ...source.payload, rawRunStatus: 'running' } })
    expect(wrapper.get('.agent-result-summary').text()).toContain('结果尚未完成核验')
    expect(wrapper.get('.agent-result-summary').text()).not.toContain('回执已保存')
    expect(wrapper.find('.agent-verification-action').exists()).toBe(false)
  })

  it('makes the limited scope of file integrity verification visible outside advanced details', () => {
    const source = verificationTask('verified')
    source.payload.finalOutput.verification.steps.push({
      call_id: 'file-call', status: 'verified',
      checks: [{ evidence: { verification_scope: 'artifact_integrity', format: 'pdf' } }],
    })
    const wrapper = mountTask(source)
    expect(wrapper.get('.agent-result-verification').text()).toContain('文件核验涵盖完整性与可读结构；业务语义仍需按任务要求验收。')
    expect(wrapper.get('.agent-result-verification').text()).not.toContain('artifact_integrity')
    expect(wrapper.get('.agent-result-evidence').attributes('open')).toBeUndefined()
  })

  it.each(['completed', 'running', 'cancelled', 'waiting_user'])('does not offer reverification for %s execution', (rawRunStatus) => {
    const source = verificationTask()
    const wrapper = mountTask({ ...source, payload: { ...source.payload, rawRunStatus } })
    expect(wrapper.find('.agent-verification-action').exists()).toBe(false)
  })

  it('does not offer reverification for a historical result without a frozen contract report', () => {
    const source = verificationTask('not_verified')
    source.payload.finalOutput.verification.steps = [{ status: 'not_verified', code: 'historical_receipt_has_no_verification_contract' }]
    const wrapper = mountTask(source)
    expect(wrapper.find('.agent-verification-action').exists()).toBe(false)
  })

  it('disables duplicate verification and refreshes without accepting transport success', async () => {
    let resolve!: (response: AgentRunResponse) => void
    const verify = vi.spyOn(agentRunsApi, 'verifyRun').mockImplementation(() => new Promise((done) => { resolve = done }))
    const retry = vi.spyOn(agentRunsApi, 'retryRun')
    const source = verificationTask()
    const wrapper = mountTask(source)
    const action = wrapper.get('.agent-verification-action')
    await action.trigger('click')
    expect(action.attributes('disabled')).toBeDefined()
    expect(action.text()).toBe('正在核验…')
    await action.trigger('click')
    expect(verify).toHaveBeenCalledTimes(1)
    expect(verify).toHaveBeenCalledWith('run-1')
    resolve({ success: true, verification: source.payload.finalOutput.verification })
    await flushPromises()
    expect(action.attributes('disabled')).toBeUndefined()
    expect(wrapper.get('.agent-result-verification [role="status"]').text()).toContain('结果仍待核验')
    expect(wrapper.emitted('refresh')).toHaveLength(1)
    expect(wrapper.props('task').status).toBe('blocked')
    expect(retry).not.toHaveBeenCalled()
    expect(wrapper.emitted('retry')).toBeUndefined()
  })

  it('refreshes an accepted report through the original task flow without setting completed locally', async () => {
    vi.spyOn(agentRunsApi, 'verifyRun').mockResolvedValue({ success: true, verification: verificationTask('verified').payload.finalOutput.verification })
    const source = verificationTask()
    const wrapper = mountTask(source)
    await wrapper.get('.agent-verification-action').trigger('click')
    await flushPromises()
    expect(wrapper.get('.agent-result-verification [role="status"]').text()).toContain('正在更新任务状态')
    expect(wrapper.emitted('refresh')).toHaveLength(1)
    expect(wrapper.props('task').status).toBe('blocked')
    expect(source.payload.finalOutput.verification.status).toBe('inconclusive')
  })

  it.each(['rejected', 'transport'])('keeps the original run on %s failure and offers verification again', async (failure) => {
    const verify = vi.spyOn(agentRunsApi, 'verifyRun')
    if (failure === 'rejected') verify.mockResolvedValue({ success: false })
    else verify.mockRejectedValue(new Error('network unavailable'))
    const retry = vi.spyOn(agentRunsApi, 'retryRun')
    const wrapper = mountTask(verificationTask())
    await wrapper.get('.agent-verification-action').trigger('click')
    await flushPromises()
    expect(wrapper.get('.agent-result-verification [role="alert"]').text()).toContain('重新核验失败')
    expect(wrapper.get('.agent-verification-action').attributes('disabled')).toBeUndefined()
    expect(wrapper.props('task').status).toBe('blocked')
    expect(retry).not.toHaveBeenCalled()
    expect(wrapper.emitted('refresh')).toHaveLength(1)
  })

  it.each(['run', 'task', 'account', 'mod', 'unmount'])('retires a late verification response when the %s changes', async (change) => {
    let resolve!: (response: AgentRunResponse) => void
    vi.spyOn(agentRunsApi, 'verifyRun').mockImplementation(() => new Promise((done) => { resolve = done }))
    const source = verificationTask()
    const wrapper = mountTask(source)
    await wrapper.get('.agent-verification-action').trigger('click')
    if (change === 'run') await wrapper.setProps({ task: { ...source, payload: { ...source.payload, activeRunId: 'run-2' } } })
    if (change === 'task') await wrapper.setProps({ task: { ...source, id: 'agent_task_task-2' } })
    if (change === 'account') productReadAccountEpoch.value++
    if (change === 'mod') writeActiveExtensionModIdToStorage('another-mod')
    if (change === 'unmount') wrapper.unmount()
    resolve({ success: true, verification: verificationTask('verified').payload.finalOutput.verification })
    await flushPromises()
    expect(wrapper.emitted('refresh')).toBeUndefined()
    if (change !== 'unmount') {
      expect(wrapper.find('.agent-result-verification [role="status"]').exists()).toBe(false)
      expect(wrapper.find('.agent-result-verification [role="alert"]').exists()).toBe(false)
      wrapper.unmount()
    }
    if (change === 'mod') writeActiveExtensionModIdToStorage(null)
  })
})
