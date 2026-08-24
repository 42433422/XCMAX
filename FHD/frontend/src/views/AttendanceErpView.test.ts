import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

const { apiFetchMock, primeCsrfCookieMock } = vi.hoisted(() => ({
  apiFetchMock: vi.fn(),
  primeCsrfCookieMock: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/utils/apiBase', () => ({ apiFetch: apiFetchMock }))
vi.mock('@/api/core', () => ({ primeCsrfCookie: primeCsrfCookieMock }))

import AttendanceErpView from './AttendanceErpView.vue'

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(payload),
  }
}

function employeeRows(page: number) {
  const count = page === 3 ? 5 : 20
  const offset = (page - 1) * 20
  return Array.from({ length: count }, (_, index) => {
    const number = offset + index + 1
    return {
      id: number,
      employee_name: `员工${number}`,
      employee_no: `E${String(number).padStart(3, '0')}`,
      department: number % 2 ? '生产部' : '销售部',
      position: '职员',
      attendance_group: '默认考勤组',
      source_system: 'legacy_attendance_migration',
    }
  })
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/employees',
        component: AttendanceErpView,
        meta: { attendanceSection: 'employees' },
      },
      {
        path: '/departments',
        component: AttendanceErpView,
        meta: { attendanceSection: 'departments' },
      },
    ],
  })
}

async function mountEmployees() {
  const router = makeRouter()
  await router.push('/employees')
  await router.isReady()
  const wrapper = mount(AttendanceErpView, { global: { plugins: [router] } })
  await flushPromises()
  return { router, wrapper }
}

describe('AttendanceErpView.vue', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
    primeCsrfCookieMock.mockClear()
    apiFetchMock.mockImplementation(async (input: string) => {
      const url = String(input)
      if (url.includes('legacy-migration-preview')) {
        return jsonResponse({ success: true, data: { available: false, already_migrated: true } })
      }
      const parsed = new URL(url, 'http://xcagi.local')
      const page = Number(parsed.searchParams.get('page') || 1)
      return jsonResponse({
        success: true,
        data: {
          items: employeeRows(page),
          total: 45,
          page,
          page_size: 20,
          source: 'erp:erp_employees',
        },
      })
    })
  })

  it('renders a bounded 20-row personnel page with human-readable ERP sources', async () => {
    const { wrapper } = await mountEmployees()

    expect(wrapper.findAll('tbody tr')).toHaveLength(20)
    expect(wrapper.text()).toContain('45名人员')
    expect(wrapper.text()).toContain('显示 1–20，共 45 条')
    expect(wrapper.text()).toContain('ERP 人员档案')
    expect(wrapper.text()).toContain('旧考勤数据 · 已归入 ERP')
    expect(wrapper.text()).not.toContain('legacy_attendance_migration')
    expect(apiFetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/erp/hr/employees?page=1&page_size=20'),
      expect.objectContaining({ credentials: 'include' }),
    )
  })

  it('pages through the ERP endpoint instead of rendering every employee at once', async () => {
    const { wrapper } = await mountEmployees()

    await wrapper.find('button[aria-label="下一页"]').trigger('click')
    await flushPromises()

    expect(apiFetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/erp/hr/employees?page=2&page_size=20'),
      expect.objectContaining({ credentials: 'include' }),
    )
    expect(wrapper.text()).toContain('显示 21–40，共 45 条')
    expect(wrapper.text()).toContain('第 2 / 3 页')
  })

  it('applies the search term from page one and keeps it visible as the active filter', async () => {
    const { wrapper } = await mountEmployees()
    await wrapper.find('button[aria-label="下一页"]').trigger('click')
    await flushPromises()

    await wrapper.find('.attendance-erp__search input').setValue('生产部')
    await wrapper.find('.attendance-erp__toolbar').trigger('submit')
    await flushPromises()

    expect(apiFetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/erp/hr/employees?page=1&page_size=20&search=%E7%94%9F%E4%BA%A7%E9%83%A8'),
      expect.objectContaining({ credentials: 'include' }),
    )
    expect(wrapper.text()).toContain('正在筛选“生产部”')
    expect(wrapper.text()).toContain('第 1 / 3 页')
  })
})
