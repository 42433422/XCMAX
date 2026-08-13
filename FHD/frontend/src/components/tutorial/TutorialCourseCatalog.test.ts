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

describe('TutorialCourseCatalog', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.courses.mockResolvedValue(courses)
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
})
