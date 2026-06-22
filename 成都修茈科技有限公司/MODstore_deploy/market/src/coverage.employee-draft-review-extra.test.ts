import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import EmployeeAiDraftReview from './components/workbench/EmployeeAiDraftReview.vue'
import { ACCESS_TOKEN_KEY } from './infrastructure/storage/tokenStore'
import { useWorkbenchStore } from './stores/workbench'

describe('EmployeeAiDraftReview coverage extras', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.setItem(ACCESS_TOKEN_KEY, 'token')
    sessionStorage.clear()
    vi.clearAllMocks()
    Object.defineProperty(window, 'prompt', {
      configurable: true,
      value: vi.fn(() => '增加边界说明'),
    })
    Object.defineProperty(window, 'open', {
      configurable: true,
      value: vi.fn(),
    })
  })

  function seedDraftStore() {
    const wb = useWorkbenchStore()
    Object.assign(wb.employeeDraftStatus, {
      phase: 'done',
      current: 'assemble',
      fatalError: '',
      manifest: {
        id: 'customer-agent',
        name: '客服员工',
        description: '处理售后问题',
        employee: { label: '客服员工' },
        employee_config_v2: {
          identity: { id: 'customer-agent', name: '客服员工', description: '处理售后问题' },
          cognition: { agent: { system_prompt: '你是客服员工。' } },
          metadata: { workflow_needs_sandbox: true },
        },
      },
    })
    Object.assign(wb.employeeDraftStages.parse_intent, {
      status: 'done',
      data: {
        id: 'customer-agent',
        name: '客服员工',
        role: '客服',
        scenario: '处理售后问题',
        industry: '零售',
        complexity: 'medium',
      },
      error: '',
    })
    Object.assign(wb.employeeDraftStages.resolve_workflow, {
      status: 'done',
      data: {
        workflow_id: 42,
        workflow_name: '售后流程',
        generated: false,
        match_score: 0.86,
      },
      error: '',
    })
    Object.assign(wb.employeeDraftStages.design_v2, {
      status: 'done',
      data: {
        perception: { inputs: ['订单号'] },
        memory: { short_term: true },
        actions: { handlers: ['refund_lookup'] },
        cognition: { agent: { system_prompt: '你是客服员工。' } },
      },
      error: '',
    })
    Object.assign(wb.employeeDraftStages.suggest_skills, {
      status: 'done',
      data: [{ name: '退款查询', brief: '查询订单退款状态', unverified: true }],
      error: '',
    })
    Object.assign(wb.employeeDraftStages.suggest_pricing, {
      status: 'done',
      data: { tier: 'basic', cny: 19, period: 'month', reasoning: '客服场景高频' },
      error: '',
    })
    Object.assign(wb.employeeDraftStages.assemble, {
      status: 'done',
      data: { ok: true },
      error: '',
    })
    wb.employeeDraftProgressMessages = ['解析完成', '草稿完成']
    wb.employeeDraftReviewMessages = [
      { id: 'm1', role: 'assistant', content: '请确认客服边界', ts: Date.now(), kind: 'clarification_question' },
    ]
    return wb
  }

  it('drives review chat, json edit, refine, publish, and authoring handoff', async () => {
    const wb = seedDraftStore()
    const fetchMock = vi.fn(async (url: RequestInfo | URL) => {
      const u = String(url)
      if (u.includes('/review-chat')) {
        return new Response(JSON.stringify({ reply: '已收到审核意见' }), { status: 200 })
      }
      if (u.includes('/refine-prompt')) {
        return new Response(JSON.stringify({
          improved_prompt: '你是客服员工。请明确拒绝越权退款。',
          diff_explanation: '增加退款边界',
        }), { status: 200 })
      }
      if (u.includes('/ai-scaffold')) {
        return new Response(JSON.stringify({ id: 'published-customer-agent' }), { status: 200 })
      }
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mount(EmployeeAiDraftReview)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(wrapper.text()).toContain('草稿已就绪')
    expect(wrapper.text()).toContain('所选工作流尚未通过沙箱测试')
    expect(vm.doneCount).toBeGreaterThan(0)
    expect(vm.statusLabel).toContain('草稿')
    expect(vm.cardClass('design_v2')).toMatchObject({ 'emp-card--done': true })
    expect(vm.badgeClass('design_v2')).toMatchObject({ 'emp-badge--done': true })
    expect(vm.badgeText('design_v2')).toBe('✓')

    await vm.sendReview()
    expect(wb.employeeDraftReviewMessages).toHaveLength(1)
    vm.reviewInput = '请补充拒绝退款边界'
    await vm.sendReview()
    await flushPromises()
    expect(wb.employeeDraftReviewMessages.some((m) => m.content.includes('审核意见'))).toBe(true)

    vm.editV2Json('perception')
    expect(vm.jsonEditTarget).toBe('perception')
    vm.jsonEditContent = '{bad json'
    vm.applyJsonEdit()
    expect(vm.jsonEditError).toContain('JSON')
    vm.jsonEditContent = JSON.stringify({ inputs: ['订单号', '手机号'] })
    vm.applyJsonEdit()
    expect(vm.jsonEditTarget).toBeNull()

    const circular: Record<string, unknown> = {}
    circular.self = circular
    expect(vm.fmtJson(circular)).toContain('[object Object]')

    await vm.openRefinePrompt()
    await flushPromises()
    expect(vm.draft.systemPrompt).toContain('越权退款')
    expect(vm.refineDiff).toContain('边界')

    await vm.publish()
    await flushPromises()
    expect(wrapper.emitted('published')?.[0]?.[0]).toBe('published-customer-agent')

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'publish failed' }), { status: 500 }))
    await vm.publish()
    await flushPromises()
    expect(vm.publishError).toContain('publish failed')

    vm.openInAuthoring()
    expect(sessionStorage.getItem('modstore_employee_prefill')).toContain('customer-agent')
    expect(window.open).toHaveBeenCalled()

    await wrapper.find('.emp-draft-close').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('renders fatal errors and emits retry when draft pipeline fails', async () => {
    const wb = seedDraftStore()
    Object.assign(wb.employeeDraftStatus, {
      phase: 'error',
      current: 'design_v2',
      fatalError: 'LLM failed',
      manifest: null,
    })
    Object.assign(wb.employeeDraftStages.parse_intent, { status: 'error', data: null, error: 'parse failed' })

    const wrapper = mount(EmployeeAiDraftReview, { props: { embedded: true } })
    await flushPromises()

    expect(wrapper.text()).toContain('LLM failed')
    await wrapper.find('.emp-draft-retry').trigger('click')
    expect(wrapper.emitted('retry')).toBeTruthy()
  })
})
