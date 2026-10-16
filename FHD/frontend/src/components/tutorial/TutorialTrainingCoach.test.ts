import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  courses: vi.fn(),
  start: vi.fn(),
  current: vi.fn(),
  enter: vi.fn(),
  leave: vi.fn(),
  verify: vi.fn(),
  reset: vi.fn(),
  reports: vi.fn(),
}))
const routerPush = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))

vi.mock('@/api/tutorialV2', () => ({ tutorialV2Api: apiMock }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ name: 'customers' }),
  useRouter: () => ({ push: routerPush }),
}))

import { useTutorialV2Store } from '@/stores/tutorialV2'
import TutorialTrainingCoach from './TutorialTrainingCoach.vue'
enableAutoUnmount(afterEach)

const step = {
  id: 'create-customer',
  title: '创建客户B',
  goal: '建立精确客户主数据',
  instruction: '在客户页面亲自创建客户B。',
  success_criteria: '教学空间中恰好一条客户B。',
  why: '销售闭环必须引用唯一客户。',
  hint: '名称必须完全一致。',
  route_name: 'customers',
  target_selector: '#tutorial-customer-target',
  location_label: '左侧菜单“组织管理”',
  completion_cue: '客户列表中出现“客户B”。',
  guide_actions: [
    {
      instruction: '点击“+ 新建客户”。',
      target_selector: '#tutorial-customer-target',
      expected_input: '',
    },
    {
      instruction: '输入客户名称。',
      target_selector: '#tutorial-customer-name',
      expected_input: '客户B',
    },
    { instruction: '点击“创建”。', target_selector: '#tutorial-customer-save', expected_input: '' },
  ],
  action_checklist: ['点击“+ 新建客户”。', '输入客户名称。', '点击“创建”。'],
  principle: '客户名称要准确且唯一。',
  required: true,
  status: 'pending' as const,
  evidence: null,
}
const activeRun = {
  id: 'run-1',
  workspace_id: 'workspace-1',
  course_id: 'master-data',
  version: 2,
  status: 'active' as const,
  current_step_id: step.id,
  attempt_count: 0,
  progress: 0,
  completed_steps: 0,
  total_steps: 1,
  generation: 1,
  teaching_space: true as const,
  steps: [step],
  started_at: '2026-08-13T00:00:00',
  completed_at: null,
}
const course = {
  id: 'master-data',
  title: '客户与产品建档',
  summary: '真实建档',
  estimated_minutes: 10,
  prerequisite_ids: [],
  version: 2,
  steps: [step],
  locked: false,
  missing_prerequisite_ids: [],
  run: activeRun,
  status: 'active' as const,
  progress: 0,
}

function mountCoach() {
  return mount(TutorialTrainingCoach, { attachTo: document.body, global: { stubs: { Teleport: true } } })
}
async function click(wrapper: ReturnType<typeof mountCoach>, label: string) {
  await wrapper.findAll('button').find(item => item.text() === label)!.trigger('click')
  await flushPromises()
}

describe('TutorialTrainingCoach', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.courses.mockResolvedValue([course])
    apiMock.current.mockResolvedValue(activeRun)
    apiMock.enter.mockResolvedValue(activeRun)
    apiMock.leave.mockResolvedValue({ ...activeRun, status: 'paused' })
  })

  afterEach(() => {
    document.querySelector('#tutorial-customer-target')?.remove()
    vi.useRealTimers()
  })

  it('shows one beginner action first and keeps explanations folded away', async () => {
    const store = useTutorialV2Store()
    store.currentRun = activeRun
    const wrapper = mountCoach()
    await flushPromises()

    expect(wrapper.text()).toContain('教学空间')
    expect(wrapper.text()).toContain('这里的练习不会改动你公司的正式数据')
    expect(wrapper.text()).toContain('现在只做这一件事')
    expect(wrapper.text()).toContain('建立精确客户主数据')
    expect(wrapper.text()).toContain('位置左侧菜单“组织管理”')
    expect(wrapper.text()).toContain('完成后你会看到')
    expect(wrapper.text()).toContain('打开操作页面')
    expect(wrapper.findAll('details')).toHaveLength(2)
    expect(wrapper.findAll('details').every((item) => item.attributes('open') === undefined)).toBe(true)
    wrapper.unmount()
  })

  it('only navigates and highlights on 打开操作页面; checking remains explicit', async () => {
    const target = document.createElement('button')
    target.id = 'tutorial-customer-target'
    document.body.appendChild(target)
    const store = useTutorialV2Store()
    store.currentRun = activeRun
    const wrapper = mountCoach()
    await flushPromises()

    await click(wrapper, '打开操作页面')
    await vi.advanceTimersByTimeAsync(100)

    expect(routerPush).toHaveBeenCalledWith({ name: 'customers' })
    expect(target.classList.contains('xcagi-tutorial-target-highlight')).toBe(true)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(target.classList.contains('xcagi-tutorial-target-highlight')).toBe(true)
    expect(apiMock.verify).not.toHaveBeenCalled()
    expect(target.getAttribute('value')).toBeNull()
    expect(wrapper.text()).toContain('照着做 · 1 / 3')
    expect(wrapper.text()).toContain('点击“+ 新建客户”。')
    wrapper.unmount()
  })

  it('keeps the current instruction visible for a wide operation target', async () => {
    const target = document.createElement('div')
    target.id = 'tutorial-customer-target'
    target.getBoundingClientRect = () => ({
      x: 20,
      y: 700,
      top: 700,
      left: 20,
      right: 1000,
      bottom: 780,
      width: 980,
      height: 80,
      toJSON: () => ({}),
    })
    document.body.appendChild(target)
    const store = useTutorialV2Store()
    store.currentRun = activeRun
    const wrapper = mountCoach()
    await flushPromises()

    await click(wrapper, '打开操作页面')
    await vi.advanceTimersByTimeAsync(100)

    expect(target.classList.contains('xcagi-tutorial-target-highlight')).toBe(true)
    expect(wrapper.text()).toContain('点击“+ 新建客户”。')
    expect(wrapper.get('.tutorial-coach').classes()).toContain('is-guide-mode')
    expect(wrapper.get('.tutorial-coach').classes()).not.toContain('is-collapsed')
    wrapper.unmount()
  })

  it('moves through micro-instructions without clicking or filling the page for the learner', async () => {
    const create = document.createElement('button')
    create.id = 'tutorial-customer-target'
    const name = document.createElement('input')
    name.id = 'tutorial-customer-name'
    let createClicks = 0
    create.addEventListener('click', () => {
      createClicks += 1
    })
    document.body.append(create, name)
    const store = useTutorialV2Store()
    store.currentRun = activeRun
    const wrapper = mountCoach()
    await flushPromises()

    await click(wrapper, '打开操作页面')
    await vi.advanceTimersByTimeAsync(100)
    await click(wrapper, '我做完了，下一条')
    await vi.advanceTimersByTimeAsync(60)

    expect(createClicks).toBe(0)
    expect(name.value).toBe('')
    expect(name.classList.contains('xcagi-tutorial-target-highlight')).toBe(true)
    expect(wrapper.text()).toContain('请准确输入')
    expect(wrapper.text()).toContain('客户B')
    expect(apiMock.verify).not.toHaveBeenCalled()
    create.remove()
    name.remove()
    wrapper.unmount()
  })

  it('explains failed evidence in Chinese without exposing internal codes or keys', async () => {
    const failedStep = {
      ...step,
      status: 'failed' as const,
      evidence: {
        step_id: step.id,
        status: 'failed' as const,
        result_code: 'customer_not_ready',
        entity_refs: [],
        counts: { customer_count: 0 },
        attempt_count: 1,
        verified_at: '2026-08-13T00:01:00',
      },
    }
    const store = useTutorialV2Store()
    const failedRun = { ...activeRun, steps: [failedStep] }
    apiMock.current.mockResolvedValue(failedRun)
    store.currentRun = failedRun
    store.verificationHint = '请确认教学空间中只有一条名称精确为“客户B”的客户。'
    const wrapper = mountCoach()
    await flushPromises()

    expect(wrapper.text()).toContain('还差一点')
    expect(wrapper.text()).toContain('客户数量：0')
    expect(wrapper.text()).toContain('名称必须完全一致')
    expect(wrapper.text()).toContain('系统会检查什么')
    expect(wrapper.text()).not.toContain('customer_count')
    expect(wrapper.text()).not.toContain('customer_not_ready')
    wrapper.unmount()
  })

  it('returns to intelligent chat after exiting a completed course', async () => {
    const completedRun = { ...activeRun, status: 'completed' as const, progress: 100 }
    const store = useTutorialV2Store()
    store.currentRun = completedRun
    apiMock.current.mockResolvedValue(completedRun)
    apiMock.leave.mockResolvedValue(completedRun)
    const wrapper = mountCoach()
    await flushPromises()

    await wrapper.get('button.btn-secondary').trigger('click')
    await flushPromises()

    expect(store.currentRun).toBeNull()
    expect(routerPush).toHaveBeenCalledWith({ name: 'chat' })
    wrapper.unmount()
  })

  it('copies required input with success and failure feedback, navigates backward and verifies only on request', async () => {
    const store = useTutorialV2Store()
    store.currentRun = activeRun
    const clipboard = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('denied'))
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: clipboard } })
    const wrapper = mountCoach()
    await flushPromises()
    await click(wrapper, '移到左侧')
    expect(wrapper.get('.tutorial-coach').classes()).toContain('is-left')
    await click(wrapper, '移到右侧')
    await click(wrapper, '收起')
    expect(wrapper.find('.tutorial-coach__focus').exists()).toBe(false)
    await click(wrapper, '展开教练')
    await click(wrapper, '打开操作页面')
    await vi.advanceTimersByTimeAsync(80)
    await click(wrapper, '我做完了，下一条')
    await click(wrapper, '复制')
    expect(clipboard).toHaveBeenCalledWith('客户B')
    expect(wrapper.text()).toContain('已复制')
    await click(wrapper, '已复制')
    expect(wrapper.text()).toContain('请手动复制')
    await vi.advanceTimersByTimeAsync(1800)
    expect(wrapper.text()).not.toContain('请手动复制')
    await click(wrapper, '上一条')
    expect(wrapper.text()).toContain('照着做 · 1 / 3')
    await click(wrapper, '指给我看')
    const target = document.createElement('button'); target.id = 'tutorial-customer-target'
    document.body.append(target); await flushPromises()
    expect(target.classList.contains('xcagi-tutorial-target-highlight')).toBe(true)
    await click(wrapper, '我做完了，下一条')
    await click(wrapper, '我做完了，下一条')
    const verify = vi.spyOn(store, 'verifyCurrent').mockResolvedValue({ evidence: { status: 'passed' } } as any)
    await click(wrapper, '我做完了，检查一下')
    expect(verify).toHaveBeenCalledWith('customers', false)
    expect(target.classList.contains('xcagi-tutorial-target-highlight')).toBe(false)
  })

  it.each(['checklist', 'instruction'])('resumes a saved course with %s fallback guidance and resets on step change', async kind => {
    const fallbackStep = { ...step, guide_actions: [], action_checklist: kind === 'checklist' ? ['第一条', '第二条'] : [],
      location_label: '', completion_cue: '', target_selector: '[' }
    const paused = { ...activeRun, status: 'paused' as const, steps: [fallbackStep] }
    const resumed = { ...paused, status: 'active' as const }
    apiMock.current.mockResolvedValue(paused); apiMock.enter.mockResolvedValue(resumed)
    const store = useTutorialV2Store(); store.currentRun = paused
    const wrapper = mountCoach(); await flushPromises()
    expect(wrapper.text()).toContain('练习已保存')
    await click(wrapper, '继续当前步骤'); await vi.advanceTimersByTimeAsync(80)
    expect(apiMock.enter).toHaveBeenCalledWith('run-1')
    expect(wrapper.text()).toContain(kind === 'checklist' ? '第一条' : step.instruction)
    expect(wrapper.text()).toContain('当前业务页面')
    expect(wrapper.text()).toContain(step.success_criteria)
    store.currentRun = { ...resumed, current_step_id: 'import-preview', steps: [{ ...fallbackStep, id: 'import-preview' }] }
    await flushPromises()
    expect(wrapper.text()).toContain('现在只做这一件事')
    expect(wrapper.get('a[download]').attributes('href')).toContain('/api/tutorial/v2/assets/business-import.xlsx')
    await click(wrapper, '保存并退出')
    expect(apiMock.leave).toHaveBeenCalledWith('run-1')
  })

  it.each(['step', 'run', 'course', 'missing'])('reviews approval evidence from %s without leaking internal identifiers', async origin => {
    const approvalRef = { type: 'approval_request', id: 17 }
    const evidence = { step_id: step.id, status: 'passed', result_code: 'verification_passed', counts: {}, entity_refs: [approvalRef] }
    const review = { ...step, route_name: 'approval-workspace', evidence: origin === 'step' ? evidence : null }
    const extra = { ...step, id: 'evidence', evidence }
    const completed = { ...activeRun, status: 'completed' as const, steps: origin === 'run' ? [review, extra] : [review] }
    apiMock.current.mockResolvedValue(completed)
    apiMock.courses.mockResolvedValue(origin === 'course' ? [{ ...course, run: { ...activeRun, steps: [extra] } }] : [])
    const store = useTutorialV2Store(); store.currentRun = completed as any
    const wrapper = mountCoach(); await flushPromises()
    await wrapper.get('.tutorial-coach__review-list button').trigger('click')
    expect(routerPush).toHaveBeenCalledWith(origin === 'missing' ? { name: 'approval-workspace' }
      : { name: 'approval-workspace', query: { request_id: '17' } })
    expect(wrapper.text()).toContain('已检查通过')
  })

  it('renders human-readable evidence values, references and fallback result labels', async () => {
    const failed = { ...step, status: 'failed', evidence: { step_id: step.id, status: 'failed', result_code: 'not-ready',
      counts: { payment_state: 'paid', approval_detail_opened: 1, unexpected: 3 },
      entity_refs: [{ type: 'customer', id: 9 }, { type: 'other', id: 10 }] } }
    const run = { ...activeRun, steps: [failed] }
    apiMock.current.mockResolvedValue(run)
    const store = useTutorialV2Store(); store.currentRun = run as any
    const wrapper = mountCoach(); await flushPromises()
    for (const label of ['收款状态：已收款', '审批详情已打开：是', '检查项：3', '客户 #9', '业务记录 #10']) expect(wrapper.text()).toContain(label)
    store.currentRun = { ...run, steps: [{ ...failed, evidence: { ...failed.evidence, counts: {}, entity_refs: [] } }] } as any
    await flushPromises()
    expect(wrapper.text()).toContain('还没有达到要求')
    store.currentRun = null; await flushPromises()
    expect(wrapper.find('.tutorial-coach').exists()).toBe(false)
  })

})
