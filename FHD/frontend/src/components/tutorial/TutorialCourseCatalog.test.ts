import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => ({
  courses: vi.fn(), start: vi.fn(), current: vi.fn(), enter: vi.fn(), leave: vi.fn(),
  verify: vi.fn(), reset: vi.fn(), reports: vi.fn(),
}))
vi.mock('@/api/tutorialV2', () => ({ tutorialV2Api: apiMock }))

import TutorialCourseCatalog from './TutorialCourseCatalog.vue'

const courses = [
  {
    id: 'master-data', title: '客户与产品建档', summary: '建立客户B和 A 产品', estimated_minutes: 10,
    prerequisite_ids: [], version: 2, steps: [], locked: false, missing_prerequisite_ids: [],
    run: null, status: 'not_started', progress: 0,
  },
  {
    id: 'sales-to-cash', title: '销售到收款完整闭环', summary: '真实销售闭环', estimated_minutes: 15,
    prerequisite_ids: ['master-data'], version: 2, steps: [], locked: true,
    missing_prerequisite_ids: ['master-data'], run: null, status: 'not_started', progress: 0,
  },
]

const activeRun = {
  id: 'run-1', workspace_id: 'workspace-1', course_id: 'master-data', version: 2,
  status: 'active', current_step_id: 'create-customer', attempt_count: 0, progress: 0,
  completed_steps: 0, total_steps: 1, generation: 1, teaching_space: true,
  steps: [], started_at: '2026-08-13T00:00:00', completed_at: null,
}

describe('TutorialCourseCatalog', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.courses.mockResolvedValue(courses)
    apiMock.start.mockResolvedValue(activeRun)
    apiMock.enter.mockResolvedValue(activeRun)
    apiMock.reset.mockResolvedValue({ ...activeRun, id: 'run-2', generation: 2 })
    apiMock.reports.mockRejectedValue(new Error('forbidden'))
  })

  it('renders statuses, progress, duration and prerequisite locking in the existing tutorial surface', async () => {
    const wrapper = mount(TutorialCourseCatalog)
    await flushPromises()
    expect(wrapper.text()).toContain('进阶教程 · 真实业务实训')
    expect(wrapper.text()).toContain('课程 1')
    expect(wrapper.text()).toContain('教程已升级')
    expect(wrapper.text()).toContain('客户与产品建档')
    expect(wrapper.text()).toContain('约 10 分钟')
    expect(wrapper.text()).toContain('进度 0%')
    expect(wrapper.text()).toContain('先完成：客户与产品建档')
    const buttons = wrapper.findAll('button').filter((button) => button.text() === '开始')
    expect(buttons).toHaveLength(2)
    expect(buttons[0].attributes('disabled')).toBeUndefined()
    expect(buttons[1].attributes('disabled')).toBeDefined()
  })

  it('keeps team reports owner/admin guarded', async () => {
    const wrapper = mount(TutorialCourseCatalog)
    await flushPromises()
    await wrapper.find('details').find('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('只有企业 owner/admin')
  })

  it('starts an unlocked course and returns to the active tutorial coach', async () => {
    const wrapper = mount(TutorialCourseCatalog)
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '开始')!.trigger('click')
    await flushPromises()

    expect(apiMock.start).toHaveBeenCalledWith('master-data')
    expect(apiMock.enter).toHaveBeenCalledWith('run-1')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('confirms a reset and renders safe team progress labels', async () => {
    apiMock.courses.mockResolvedValue([{ ...courses[0], run: activeRun, status: 'active' }])
    apiMock.reports.mockResolvedValue([{
      user_id: 2,
      user_name: '教学成员',
      course_id: 'master-data',
      status: 'completed',
      progress: 100,
      attempt_count: 2,
    }])
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(TutorialCourseCatalog)
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '重置')!.trigger('click')
    await flushPromises()
    expect(confirm).toHaveBeenCalled()
    expect(apiMock.reset).toHaveBeenCalledWith('run-1')
    expect(wrapper.emitted('close')).toHaveLength(1)

    await wrapper.find('details').find('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('共 1 条课程运行记录')
    expect(wrapper.text()).toContain('教学成员 · 客户与产品建档 · 已完成 · 100% · 尝试 2 次')
    confirm.mockRestore()
  })
})
