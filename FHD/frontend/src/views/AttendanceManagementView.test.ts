import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AttendanceManagementView from '../../../XCAGI/mods/attendance-industry/frontend/views/AttendanceManagementView.vue'

const apiFetch = vi.fn()

vi.mock('@/utils/apiBase', () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }))
vi.mock('@/utils/appDialog', () => ({ appConfirm: vi.fn(async () => true) }))

function response(data: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: async () => ({ success: true, data }),
  })
}

function mountView(section: 'personnel' | 'departments' | 'schedules' | 'records') {
  return mount(AttendanceManagementView, {
    props: { section },
    global: {
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
  })
}

describe('AttendanceManagementView', () => {
  beforeEach(() => {
    apiFetch.mockReset()
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  })

  it.each(['personnel', 'departments'] as const)('edits %s in a modal and cancels without changing the list', async (section) => {
    apiFetch.mockReturnValue(response({ items: [{ id: 2, employee_name: '张三', department: '生产部' }], total: 80 }))
    const wrapper = mountView(section)
    await flushPromises()
    expect(wrapper.find('dialog').attributes('open')).toBeUndefined()
    await wrapper.findAll('tbody button').find(button => button.text() === '编辑')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('dialog').attributes('open')).toBe('')
    expect(wrapper.find('dialog input').element.value).toBe(section === 'personnel' ? '张三' : '生产部')
    await wrapper.find('dialog').trigger('cancel')
    await flushPromises()
    expect(wrapper.find('dialog').attributes('open')).toBeUndefined()
    expect(wrapper.find('tbody').text()).toContain('生产部')
    expect(apiFetch.mock.calls.every(([, options]) => !options?.method)).toBe(true)
    wrapper.unmount()
  })

  it('keeps the current page and rendered table while saving and refreshing', async () => {
    let finishRefresh: ((value: unknown) => void) | undefined
    let saved = false
    apiFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (options?.method === 'PUT') { saved = true; return response({}) }
      if (saved && url.includes('/employees?')) return new Promise(resolve => { finishRefresh = resolve })
      return response({ items: [{ id: 2, employee_name: '张三', department: '生产部' }], total: 80 })
    })
    const wrapper = mountView('personnel')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '下一页')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('tbody button').find(button => button.text() === '编辑')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('dialog button').find(button => button.text() === '保存')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('tbody').exists()).toBe(true)
    expect(wrapper.text()).toContain('第 2 / 4 页')
    expect(apiFetch).toHaveBeenCalledWith(expect.stringContaining('page=2'), undefined)
    finishRefresh!(await response({ items: [{ id: 2, employee_name: '张三', department: '生产部' }], total: 80 }))
    await flushPromises()
    expect(wrapper.find('dialog').attributes('open')).toBeUndefined()
    wrapper.unmount()
  })

  it('renders the real personnel-management list from the attendance roster', async () => {
    apiFetch.mockImplementation((url: string) => {
      if (url.includes('/departments?')) return response({ items: [{ department: '生产部' }] })
      return response({
        items: [
          {
            id: 1,
            employee_name: '张三',
            employee_no: 'E001',
            department: '生产部',
            main_department: '制造中心',
            attendance_group: '计时',
            position: '木工',
          },
        ],
        total: 1,
      })
    })

    const wrapper = mountView('personnel')
    await flushPromises()

    expect(wrapper.text()).toContain('人员管理')
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('生产部')
    expect(apiFetch).toHaveBeenCalledWith(expect.stringContaining('/api/mod/attendance-industry/employees?'), undefined)
    expect(wrapper.text()).not.toContain('考勤看板')
    // The shared page-view flex/overflow rules shrink the header and clip pagination.
    expect(wrapper.classes()).toContain('attendance-management')
    expect(wrapper.classes()).not.toContain('page-view')
  })

  it('renders department counts', async () => {
    apiFetch.mockReturnValue(
      response({
        items: [{ id: 2, department: '生产部', main_department: '制造中心', attendance_group: '计时', employee_count: 12 }],
        total: 1,
      }),
    )

    const wrapper = mountView('departments')
    await flushPromises()

    expect(wrapper.text()).toContain('部门管理')
    expect(wrapper.text()).toContain('制造中心')
    expect(wrapper.text()).toContain('12')
  })

  it('renders schedule resources instead of a statistics dashboard', async () => {
    apiFetch.mockReturnValue(
      response({
        schedule_groups: [
          {
            name: '工厂正班',
            shift_type: '固定班制',
            headcount: '按导出表统计',
            lines: ['08:00-12:00 / 13:30-17:30'],
          },
        ],
        lines: ['周日按加班处理'],
      }),
    )

    const wrapper = mountView('schedules')
    await flushPromises()

    expect(wrapper.text()).toContain('排班资源')
    expect(wrapper.text()).toContain('工厂正班')
    expect(wrapper.text()).toContain('周日按加班处理')
  })
})
