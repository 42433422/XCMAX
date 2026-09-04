import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }))

vi.mock('@/utils/apiBase', () => ({ apiFetch }))

import DashboardView from '../../../XCAGI/mods/attendance-industry/frontend/views/DashboardView.vue'

function response(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

function mountView() {
  return mount(DashboardView, {
    global: {
      stubs: { RouterLink: RouterLinkStub },
    },
  })
}

describe('Attendance dashboard', () => {
  it('renders live attendance metrics, department distribution and latest import', async () => {
    apiFetch.mockResolvedValueOnce(
      response({
        success: true,
        data: {
          employees_total: 72,
          departments_total: 8,
          daily_records_total: 2232,
          anomaly_records_total: 14,
          months_total: 1,
          latest_month: '2026-08',
          date_from: '2026-08-01',
          date_to: '2026-08-31',
          latest_import: {
            source_file: '/workspace/太阳鸟8月考勤.xlsx',
            month_label: '2026-08',
            rows_in: 4309,
            rows_written: 2232,
            imported_at: '2026-09-01T14:30:00',
          },
          department_breakdown: [
            { department: '生产部', employees: 42 },
            { department: '行政部', employees: 8 },
          ],
          readiness: 'ready',
        },
      }),
    )

    const wrapper = mountView()
    await flushPromises()

    expect(apiFetch).toHaveBeenCalledWith('/api/mod/attendance-industry/attendance/dashboard')
    expect(wrapper.text()).toContain('考勤看板')
    expect(wrapper.text()).toContain('72')
    expect(wrapper.text()).toContain('2,232')
    expect(wrapper.text()).toContain('14')
    expect(wrapper.text()).toContain('生产部')
    expect(wrapper.text()).toContain('太阳鸟8月考勤.xlsx')
    expect(wrapper.text()).toContain('考勤数据已就绪')
  })

  it('shows the upload action when roster exists but attendance records are missing', async () => {
    apiFetch.mockResolvedValueOnce(
      response({
        success: true,
        data: {
          employees_total: 80,
          departments_total: 11,
          daily_records_total: 0,
          anomaly_records_total: 0,
          months_total: 0,
          latest_month: '',
          date_from: '',
          date_to: '',
          latest_import: null,
          department_breakdown: [{ department: '生产部', employees: 30 }],
          readiness: 'needs_records',
        },
      }),
    )

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('人员已就绪，等待考勤明细')
    expect(wrapper.text()).toContain('去上传转换')
    expect(wrapper.text()).toContain('尚无考勤导入记录')
  })

  it('renders a retry state when the dashboard API fails', async () => {
    apiFetch.mockResolvedValueOnce(response({ success: false, message: '读取失败' }, false, 500))

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('读取失败')
    expect(wrapper.text()).toContain('重新加载')
  })
})
