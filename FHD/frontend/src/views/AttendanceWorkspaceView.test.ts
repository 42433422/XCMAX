import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '@/utils/apiBase'

import AttendanceWorkspaceView from '../../../XCAGI/mods/attendance-industry/frontend/views/AttendanceWorkspaceView.vue'
import { modMenu, modRoutes } from '../../../XCAGI/mods/attendance-industry/frontend/routes.js'
import { ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU, buildAttendanceIndustryModStub } from '@/constants/sunbirdClientMod'
import manifest from '../../../XCAGI/mods/attendance-industry/manifest.json'

vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn() }))

describe('AttendanceWorkspaceView', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockImplementation(async () => new Response(JSON.stringify({ custom_features: ['attendance-convert'] })))
  })
  it('keeps the manifest, fallback and runtime menu at one workspace entry', () => {
    expect(manifest.frontend.menu).toEqual(modMenu)
    expect(ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU).toEqual(modMenu)
    expect(buildAttendanceIndustryModStub().frontend?.pro_entry_path).toBe('/attendance-industry')
    expect(manifest.frontend.pro_entry_path).toBe('/attendance-industry')
  })

  it('navigates all sections within the workspace and supports browser back', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        ...modRoutes.map((route) => (route.redirect ? route : { ...route, component: AttendanceWorkspaceView })),
        { path: '/mod/sunbird-attendance-custom/convert', component: { template: '<div data-test="independent-custom">独立定制包</div>' } },
      ],
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
    expect(links.map((link) => link.text())).toEqual(['部门管理', '人员管理', '排班资源', '考勤记录', '考勤定制 Mod'])
    for (const [index, section] of ['departments', 'personnel', 'schedules', 'records'].entries()) {
      await links[index].trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.path).toBe(`/attendance-industry/${section}`)
      expect(wrapper.findAll('h1')).toHaveLength(1)
      expect(wrapper.find('nav [aria-current="page"]').text()).toBe(links[index].text())
      if (index < 4) expect(wrapper.find('[data-test="management"]').text()).toBe(section)
    }
    await links[4].trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/mod/sunbird-attendance-custom/convert')
    expect(wrapper.find('[data-test="independent-custom"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="conversion"]').exists()).toBe(false)
    router.back()
    await new Promise((resolve) => setTimeout(resolve, 0))
    await flushPromises()
    expect(wrapper.find('[data-test="management"]').text()).toBe('records')
  })

  it.each(['convert', 'settings'])('denies direct custom %s links without entitlement', async (section) => {
    vi.mocked(apiFetch).mockImplementation(async () => new Response(JSON.stringify({ custom_features: [] })))
    const wrapper = mount(AttendanceWorkspaceView, {
      props: { section },
      global: { stubs: { RouterLink: true, HomeView: true, AttendanceSettingsView: true, AttendanceManagementView: true } },
    })
    await flushPromises()
    expect(wrapper.findAll('nav router-link-stub')).toHaveLength(4)
    expect(wrapper.text()).toContain('未开通考勤表转换定制功能')
    expect(wrapper.find('home-view-stub').exists()).toBe(false)
    expect(wrapper.find('attendance-settings-view-stub').exists()).toBe(false)
  })

  it('fails closed when the capability request fails', async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error('offline'))
    const wrapper = mount(AttendanceWorkspaceView, {
      props: { section: 'convert' },
      global: { stubs: { RouterLink: true, HomeView: true, AttendanceSettingsView: true } },
    })
    await flushPromises()
    expect(wrapper.find('home-view-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain('未开通')
  })
})
