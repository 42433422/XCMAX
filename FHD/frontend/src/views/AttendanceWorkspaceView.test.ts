import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'

import AttendanceWorkspaceView from '../../../XCAGI/mods/attendance-industry/frontend/views/AttendanceWorkspaceView.vue'
import { modMenu, modRoutes } from '../../../XCAGI/mods/attendance-industry/frontend/routes.js'
import { ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU, buildAttendanceIndustryModStub } from '@/constants/sunbirdClientMod'
import manifest from '../../../XCAGI/mods/attendance-industry/manifest.json'

vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn() }))

describe('AttendanceWorkspaceView', () => {
  it('keeps the manifest, fallback and runtime menu at one workspace entry', () => {
    expect(manifest.frontend.menu).toEqual(modMenu)
    expect(ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU).toEqual(modMenu)
    expect(buildAttendanceIndustryModStub().frontend?.pro_entry_path).toBe('/attendance-industry')
    expect(manifest.frontend.pro_entry_path).toBe('/attendance-industry')
  })

  it('navigates all sections within the workspace and supports browser back', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: modRoutes.map((route) => (route.redirect ? route : { ...route, component: AttendanceWorkspaceView })),
    })
    await router.push('/attendance-industry')
    const wrapper = mount(
      { template: '<router-view />' },
      {
        global: {
          plugins: [router],
          stubs: {
            AttendanceManagementView: { props: ['section'], template: '<div data-test="management">{{ section }}</div>' },
            HomeView: { template: '<div data-test="conversion">转换</div>' },
            AttendanceSettingsView: { template: '<div data-test="settings">设置</div>' },
          },
        },
      },
    )
    await flushPromises()
    expect(wrapper.find('h1').text()).toBe('考勤工作区')
    expect(wrapper.find('[data-test="management"]').text()).toBe('personnel')
    const links = wrapper.findAll('nav a')
    expect(links.map((link) => link.text())).toEqual(['部门管理', '人员管理', '排班资源', '考勤记录', '考勤表转换', '考勤设置'])
    for (const [index, section] of ['departments', 'personnel', 'schedules', 'records', 'convert', 'settings'].entries()) {
      await links[index].trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.path).toBe(`/attendance-industry/${section}`)
      expect(wrapper.findAll('h1')).toHaveLength(1)
      expect(wrapper.find('nav [aria-current="page"]').text()).toBe(links[index].text())
      if (index < 4) expect(wrapper.find('[data-test="management"]').text()).toBe(section)
    }
    router.back()
    await new Promise((resolve) => setTimeout(resolve, 0))
    await flushPromises()
    expect(wrapper.find('[data-test="conversion"]').exists()).toBe(true)
  })
})
