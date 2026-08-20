import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

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

vi.mock('@/api/tutorialV2', () => ({ tutorialV2Api: apiMock }))

import { activeTutorialRunAllowsRoute, tutorialRunAllowsRoute, useTutorialV2Store } from './tutorialV2'

const step = {
  id: 'create-customer',
  title: '创建客户B',
  goal: '建客户',
  instruction: '亲自创建',
  success_criteria: '恰好一条',
  why: '主数据唯一',
  hint: '精确名称',
  route_name: 'customers',
  target_selector: 'button',
  location_label: '组织管理',
  completion_cue: '看到客户B',
  guide_actions: [{ instruction: '点击新建', target_selector: 'button', expected_input: '' }],
  action_checklist: ['点击新建'],
  principle: '',
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

describe('tutorial V2 store', () => {
  it('only allows routes declared by an active or completed tutorial run', () => {
    expect(tutorialRunAllowsRoute(activeRun, 'customers')).toBe(true)
    expect(tutorialRunAllowsRoute(activeRun, 'products')).toBe(false)
    expect(tutorialRunAllowsRoute({ ...activeRun, status: 'paused' }, 'customers')).toBe(false)
    expect(tutorialRunAllowsRoute({ ...activeRun, status: 'completed' }, 'customers')).toBe(true)
    expect(tutorialRunAllowsRoute(null, 'customers')).toBe(false)

    const store = useTutorialV2Store()
    store.currentRun = activeRun
    expect(activeTutorialRunAllowsRoute('customers')).toBe(true)
    expect(activeTutorialRunAllowsRoute('products')).toBe(false)
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.courses.mockResolvedValue([course])
    apiMock.start.mockResolvedValue(activeRun)
    apiMock.enter.mockResolvedValue(activeRun)
    apiMock.current.mockResolvedValue(activeRun)
    apiMock.leave.mockResolvedValue({ ...activeRun, status: 'paused' })
    apiMock.reset.mockResolvedValue({ ...activeRun, id: 'run-2', generation: 2 })
    apiMock.reports.mockResolvedValue([])
  })

  it('starts and enters a server run without timed auto progress', async () => {
    vi.useFakeTimers()
    const store = useTutorialV2Store()
    await store.startCourse('master-data')
    expect(apiMock.start).toHaveBeenCalledWith('master-data')
    expect(apiMock.enter).toHaveBeenCalledWith('run-1')
    expect(store.currentStep?.id).toBe('create-customer')

    await vi.advanceTimersByTimeAsync(60_000)
    expect(apiMock.verify).not.toHaveBeenCalled()
    expect(store.currentRun?.progress).toBe(0)
    vi.useRealTimers()
  })

  it('keeps a failed verification actionable and only unlocks from server response', async () => {
    const store = useTutorialV2Store()
    store.currentRun = activeRun
    store.markTargetVisited()
    apiMock.verify.mockResolvedValue({
      run: { ...activeRun, attempt_count: 1 },
      evidence: { status: 'failed', result_code: 'customer_not_ready' },
      hint: '请确认教学空间中只有一条客户B。',
    })
    await store.verifyCurrent('customers')
    expect(apiMock.verify).toHaveBeenCalledWith('run-1', 'create-customer', {
      visited_route: 'customers',
      target_visible: false,
    })
    expect(store.currentRun?.progress).toBe(0)
    expect(store.verificationHint).toContain('客户B')

    apiMock.verify.mockResolvedValue({
      run: { ...activeRun, status: 'completed', progress: 100, completed_steps: 1 },
      evidence: { status: 'passed', result_code: 'verification_passed' },
      hint: '验证通过，下一步已解锁。',
    })
    await store.verifyCurrent('customers')
    expect(store.currentRun?.status).toBe('completed')
    expect(store.currentRun?.progress).toBe(100)
  })

  it('saves on leave and resumes the same durable run', async () => {
    const store = useTutorialV2Store()
    store.currentRun = activeRun
    await store.leaveCurrent()
    expect(store.currentRun?.status).toBe('paused')
    expect(store.verificationHint).toContain('进度已保存')
    await store.restoreCurrent()
    await store.enterRun('run-1')
    expect(apiMock.current).toHaveBeenCalled()
    expect(apiMock.enter).toHaveBeenCalledWith('run-1')
    expect(store.currentRun?.id).toBe('run-1')
  })

  it('starts a fresh practice when the user resets a course', async () => {
    const store = useTutorialV2Store()
    store.courses = [course]

    await store.resetCourse('run-1')

    expect(apiMock.reset).toHaveBeenCalledWith('run-1')
    expect(store.currentRun).toMatchObject({ id: 'run-2', generation: 2 })
    expect(store.verificationHint).toContain('新的练习已经开始')
    expect(store.verificationHint).not.toContain('代次')
    expect(apiMock.courses).toHaveBeenCalled()
  })
})
