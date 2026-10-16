import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import KellaiCustomerInbox from './KellaiCustomerInbox.vue'

const kellaiMocks = vi.hoisted(() => ({
  status: vi.fn(),
  start: vi.fn(),
  dataStatus: vi.fn(),
  customers: vi.fn(),
  conversations: vi.fn(),
  latestDraft: vi.fn(),
  followUpOverview: vi.fn(),
  followUpTasks: vi.fn(),
  generateDraft: vi.fn(),
  decideDraft: vi.fn(),
  createFollowUpTask: vi.fn(),
  decideFollowUpTask: vi.fn(),
  disconnect: vi.fn(),
}))

vi.mock('@/api/kellaiBinding', () => ({
  default: kellaiMocks,
  kellaiBindingApi: kellaiMocks,
}))

const connectedStatus = {
  state: 'connected' as const,
  connection: {
    authorized_scopes: ['customer_profiles.read', 'customer_conversations.read'],
    authorized_by: { display_name: '企业负责人' },
  },
  available_scopes: [],
}

describe('KellaiCustomerInbox', () => {
  beforeEach(() => {
    Object.values(kellaiMocks).forEach(mock => mock.mockReset())

    kellaiMocks.status.mockResolvedValue(connectedStatus)
    kellaiMocks.dataStatus.mockResolvedValue({ customer_count: 1, unread_message_count: 2 })
    kellaiMocks.customers.mockResolvedValue([
      {
        customer_id: 7,
        display_name: '王女士',
        stage_label: '意向客户',
        channel_sources: ['wecom'],
        last_message_preview: '请问什么时候可以交付？',
      },
    ])
    kellaiMocks.conversations.mockResolvedValue([
      {
        id: 'm2',
        customer_id: 7,
        direction: 'outbound',
        content: '我来确认交付时间。',
        created_at: '2026-07-15T10:02:00Z',
        channel_type: 'wecom',
      },
      {
        id: 'm1',
        customer_id: 7,
        direction: 'inbound',
        content: '请问什么时候可以交付？',
        created_at: '2026-07-15T10:01:00Z',
        channel_type: 'wecom',
        ai_intent: '询问交付时间',
      },
    ])
    kellaiMocks.latestDraft.mockResolvedValue(null)
    kellaiMocks.followUpOverview.mockResolvedValue({
      tasks: [],
      metrics: {
        total: 0,
        open: 0,
        completed: 0,
        failed: 0,
        cancelled: 0,
        outcomes: { success: 0, no_result: 0, failed: 0 },
        success_rate: null,
      },
    })
    kellaiMocks.followUpTasks.mockResolvedValue([])
    kellaiMocks.generateDraft.mockResolvedValue({
      draft_id: 'draft-1',
      customer_id: 7,
      summary: '客户正在确认交付时间。',
      intent: '询问交期',
      risk_level: 'medium',
      next_action: '核实计划后再回复',
      reply_draft: '您好，我正在核实交付计划，确认后第一时间回复您。',
      evidence_message_ids: ['m1', 'm2'],
      status: 'pending_approval',
      created_at: '2026-07-15T10:03:00Z',
    })
    kellaiMocks.decideDraft.mockImplementation(async (_draftId: string, decision: string) => ({
      ...(await kellaiMocks.generateDraft()),
      status: decision === 'approve' ? 'approved_for_manual_send' : 'rejected',
    }))
    const followUpTask = {
      task_id: 'task-1',
      customer_id: 7,
      source_draft_id: 'draft-1',
      title: '客户跟进 · 询问交期',
      description: '核实计划后再回复',
      priority: 'normal',
      status: 'open',
      due_at: '2026-07-16T10:03:00Z',
      created_at: '2026-07-15T10:03:00Z',
    }
    kellaiMocks.createFollowUpTask.mockResolvedValue(followUpTask)
    kellaiMocks.decideFollowUpTask.mockImplementation(async (_taskId: string, decision: string, outcomeResult: string) => ({
      ...followUpTask,
      status: decision === 'complete' ? (outcomeResult === 'failed' ? 'failed' : 'completed') : 'cancelled',
      outcome_result: decision === 'complete' ? outcomeResult : '',
    }))
    kellaiMocks.start.mockResolvedValue({
      request_id: 'req-1',
      expires_at: '2026-07-15T10:15:00Z',
    })
    kellaiMocks.disconnect.mockResolvedValue(undefined)
    ;(window as Window & { xcagiDesktop?: unknown }).xcagiDesktop = undefined
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    ;(window as Window & { xcagiDesktop?: unknown }).xcagiDesktop = undefined
  })

  it('renders authorized customers and their conversations inside XCMAX as read-only', async () => {
    const wrapper = mount(KellaiCustomerInbox)
    await flushPromises()

    expect(wrapper.text()).toContain('客户消息 · 客来来')
    expect(wrapper.text()).toContain('王女士')
    expect(wrapper.text()).toContain('企业微信')
    expect(wrapper.text()).toContain('请问什么时候可以交付？')
    expect(wrapper.text()).toContain('我来确认交付时间。')
    expect(wrapper.text()).toContain('不能自动向客户发送消息')
    expect(wrapper.find('form').exists()).toBe(false)
    expect(kellaiMocks.conversations).toHaveBeenCalledWith(7, 100)

    const messageText = wrapper.find('.kellai-inbox__messages').text()
    expect(messageText.indexOf('请问什么时候可以交付？')).toBeLessThan(messageText.indexOf('我来确认交付时间。'))
    wrapper.unmount()
  })

  it('starts local pairing from the client inbox and opens the Kellai desktop app', async () => {
    kellaiMocks.status.mockResolvedValue({
      state: 'not_connected',
      available_scopes: [{ id: 'customer_profiles.read', label: '读取客户档案', description: '只读客户资料' }],
    })
    const openKellaiDesktop = vi.fn().mockResolvedValue({ ok: true })
    ;(
      window as Window & {
        xcagiDesktop?: { openKellaiDesktop?: () => Promise<{ ok?: boolean }> }
      }
    ).xcagiDesktop = { openKellaiDesktop }

    const wrapper = mount(KellaiCustomerInbox)
    await flushPromises()
    expect(wrapper.text()).toContain('绑定客来来')

    await wrapper.find('.kellai-inbox__button.is-primary').trigger('click')
    await flushPromises()

    expect(kellaiMocks.start).toHaveBeenCalledOnce()
    expect(openKellaiDesktop).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('generates an AI reply draft and requires explicit approval without sending', async () => {
    const wrapper = mount(KellaiCustomerInbox)
    await flushPromises()

    const generateButton = wrapper.findAll('button').find((button) => button.text().includes('生成摘要与草稿'))
    expect(generateButton).toBeTruthy()
    await generateButton!.trigger('click')
    await flushPromises()

    expect(kellaiMocks.generateDraft).toHaveBeenCalledWith(7)
    expect(wrapper.text()).toContain('客户正在确认交付时间。')
    expect(wrapper.text()).toContain('您好，我正在核实交付计划')
    expect(wrapper.text()).toContain('等待人工批准')

    const approveButton = wrapper.findAll('button').find((button) => button.text().includes('批准为手动发送草稿'))
    expect(approveButton).toBeTruthy()
    await approveButton!.trigger('click')
    await flushPromises()

    expect(kellaiMocks.decideDraft).toHaveBeenCalledWith('draft-1', 'approve')
    expect(wrapper.text()).toContain('已人工批准；系统仍不会自动发送')
    expect(wrapper.find('form').exists()).toBe(false)
    wrapper.unmount()
  })

  it('executes only the approved bounded action and tracks it to completion', async () => {
    const wrapper = mount(KellaiCustomerInbox)
    await flushPromises()

    const generateButton = wrapper.findAll('button').find((button) => button.text().includes('生成摘要与草稿'))
    await generateButton!.trigger('click')
    await flushPromises()

    const createTaskButton = wrapper.findAll('button').find((button) => button.text().includes('批准并创建跟进任务'))
    expect(createTaskButton).toBeTruthy()
    await createTaskButton!.trigger('click')
    await flushPromises()

    expect(kellaiMocks.createFollowUpTask).toHaveBeenCalledWith('draft-1')
    expect(wrapper.text()).toContain('客户跟进 · 询问交期')
    expect(wrapper.text()).toContain('不会写回客来来，也不会联系客户')

    const completeButton = wrapper.findAll('button').find((button) => button.text().includes('完成 · 有效'))
    expect(completeButton).toBeTruthy()
    await completeButton!.trigger('click')
    await flushPromises()

    expect(kellaiMocks.decideFollowUpTask).toHaveBeenCalledWith('task-1', 'complete', 'success')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('成功率 100%')
    expect(wrapper.find('form').exists()).toBe(false)
    wrapper.unmount()
  })

  it('revokes the local read token after explicit customer confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    kellaiMocks.status.mockResolvedValueOnce(connectedStatus).mockResolvedValueOnce({ state: 'not_connected', available_scopes: [] })

    const wrapper = mount(KellaiCustomerInbox)
    await flushPromises()
    await wrapper.find('.kellai-inbox__link').trigger('click')
    await flushPromises()

    expect(kellaiMocks.disconnect).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('连接客来来客户 IM')
    wrapper.unmount()
  })

  it('renders image messages from content_type/media_url', async () => {
    kellaiMocks.conversations.mockResolvedValue([
      {
        id: 'img-1',
        customer_id: 7,
        direction: 'inbound',
        content: '[图片]',
        content_type: 'image',
        metadata: { media_url: 'https://cdn.example.com/demo.png' },
        created_at: '2026-07-15T10:01:00Z',
        channel_type: 'wechat',
      },
    ])
    const wrapper = mount(KellaiCustomerInbox)
    await flushPromises()
    const img = wrapper.find('img.kellai-inbox__message-image')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('https://cdn.example.com/demo.png')
    wrapper.unmount()
  })
  async function clickButton(wrapper: ReturnType<typeof mount>, text: string) {
    await wrapper.findAll('button').find(button => button.text().includes(text))!.trigger('click')
    await flushPromises()
  }

  it('polls pending authorization, loads customers once connected and stops when unmounted', async () => {
    vi.useFakeTimers()
    kellaiMocks.status.mockResolvedValueOnce({ state: 'pending' })
    const wrapper = mount(KellaiCustomerInbox)
    await flushPromises()
    expect(wrapper.get('.kellai-inbox__status').text()).toBe('等待授权')
    await vi.advanceTimersByTimeAsync(4000)
    expect(wrapper.get('.kellai-inbox__status').text()).toBe('已连接')
    expect(kellaiMocks.status).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(4000)
    expect(kellaiMocks.status).toHaveBeenCalledTimes(2)
    wrapper.unmount(); await vi.advanceTimersByTimeAsync(4000)
    expect(kellaiMocks.status).toHaveBeenCalledTimes(2)
  })

  it('selects a different customer, avoids reloading an unchanged selection and clears empty history', async () => {
    kellaiMocks.customers.mockResolvedValue([{ customer_id: 7, display_name: 'A' }, { customer_id: 8, display_name: '', channel_sources: ['wechat', 'custom'] }])
    const wrapper = mount(KellaiCustomerInbox); await flushPromises()
    await wrapper.findAll('.kellai-inbox__customer')[0].trigger('click'); await flushPromises()
    expect(kellaiMocks.conversations).toHaveBeenCalledTimes(1)
    kellaiMocks.conversations.mockRejectedValueOnce(new Error('读取会话失败'))
    await wrapper.findAll('.kellai-inbox__customer')[1].trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe('读取会话失败')
    expect(kellaiMocks.conversations).toHaveBeenLastCalledWith(8, 100)
    kellaiMocks.customers.mockResolvedValue([])
    await clickButton(wrapper, '刷新')
    expect(wrapper.text()).toContain('暂无已授权的真实客户会话')
    expect(wrapper.find('.kellai-inbox__copilot').exists()).toBe(false)
    wrapper.unmount()
  })

  it.each([
    ['status', '刷新', '无法读取客来来客户会话'],
    ['generateDraft', '生成摘要与草稿', 'AI 摘要与回复草稿生成失败'],
    ['decideDraft', '拒绝草稿', '草稿审批失败'],
    ['createFollowUpTask', '批准并创建跟进任务', '跟进任务创建失败'],
    ['decideFollowUpTask', '取消任务', '跟进任务更新失败'],
    ['disconnect', '解除绑定', '解除绑定失败'],
  ] as const)('reports %s failures and leaves actions retryable', async (method, label, fallback) => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(KellaiCustomerInbox); await flushPromises()
    if (['decideDraft', 'createFollowUpTask', 'decideFollowUpTask'].includes(method)) await clickButton(wrapper, '生成摘要与草稿')
    if (method === 'decideFollowUpTask') await clickButton(wrapper, '批准并创建跟进任务')
    for (const [failure, expected] of [[new Error('暂时离线'), '暂时离线'], [null, fallback]]) {
      kellaiMocks[method].mockRejectedValueOnce(failure)
      await clickButton(wrapper, label)
      expect(wrapper.get('[role="alert"]').text()).toBe(expected)
      expect(wrapper.findAll('button').find(button => button.text().includes(label))!.attributes('disabled')).toBeUndefined()
    }
    wrapper.unmount()
  })

  it.each([['complete', 'no_result', '完成 · 暂无结果', '暂无结果'], ['complete', 'failed', '执行失败', '失败'], ['cancel', '', '取消任务', '已取消']])(
    'records follow-up %s %s and recalculates the visible metrics', async (decision, outcome, label, result) => {
      const wrapper = mount(KellaiCustomerInbox); await flushPromises()
      await clickButton(wrapper, '生成摘要与草稿'); await clickButton(wrapper, '批准并创建跟进任务')
      await clickButton(wrapper, label)
      expect(kellaiMocks.decideFollowUpTask).toHaveBeenCalledWith('task-1', decision, outcome)
      expect(wrapper.get('.kellai-inbox__task-item').text()).toContain(result)
      expect(wrapper.find('.kellai-inbox__task-actions').exists()).toBe(false)
      expect(wrapper.get('.kellai-inbox__task-list-head').text()).toContain(outcome ? '成功率 0%' : '成功率 —')
      wrapper.unmount()
    })

  it('copies only an approved draft and reports unavailable clipboard access', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mount(KellaiCustomerInbox); await flushPromises()
    await clickButton(wrapper, '生成摘要与草稿'); await clickButton(wrapper, '批准为手动发送草稿')
    await clickButton(wrapper, '复制草稿')
    expect(writeText).toHaveBeenCalledWith('您好，我正在核实交付计划，确认后第一时间回复您。')
    expect(wrapper.text()).toContain('已复制')
    writeText.mockRejectedValueOnce(new Error('blocked')); await clickButton(wrapper, '已复制')
    expect(wrapper.get('[role="alert"]').text()).toContain('请手动选择文本复制')
    wrapper.unmount(); vi.unstubAllGlobals()
  })

  it('handles desktop and browser pairing failures, cancellation and rejected drafts', async () => {
    const wrapper = mount(KellaiCustomerInbox); await flushPromises()
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    await clickButton(wrapper, '解除绑定'); expect(kellaiMocks.disconnect).not.toHaveBeenCalled()
    await clickButton(wrapper, '生成摘要与草稿'); await clickButton(wrapper, '拒绝草稿')
    expect(wrapper.text()).toContain('此草稿已拒绝，不可用于发送')
    kellaiMocks.status.mockResolvedValue({ state: 'offline' }); await clickButton(wrapper, '刷新')
    expect(wrapper.get('.kellai-inbox__status').text()).toBe('客来来未运行')
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    await clickButton(wrapper, '打开客来来')
    expect(open).toHaveBeenCalledWith('kellai://settings?tab=xcmax', '_blank', 'noopener,noreferrer')
    expect(wrapper.get('[role="alert"]').text()).toContain('请使用 XCMAX 桌面端')
    ;(window as any).xcagiDesktop = { openKellaiDesktop: vi.fn().mockResolvedValue({ ok: false, reason: '客来来未安装' }) }
    await clickButton(wrapper, '绑定客来来')
    expect(wrapper.get('[role="alert"]').text()).toBe('客来来未安装')
    wrapper.unmount()
  })

})
