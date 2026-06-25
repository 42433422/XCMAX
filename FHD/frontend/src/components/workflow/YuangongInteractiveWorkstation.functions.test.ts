import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const mockPush = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
}))

vi.mock('@/constants/yuangongAssets', () => ({
  YUANGONG_DESK_PNG: '/desk.png',
  YUANGONG_DESK_SVG: '/desk.svg',
  YUANGONG_STAFF_PNG: '/staff.png',
  YUANGONG_STAFF_SVG: '/staff.svg',
  YUANGONG_STAFF_BUSY_PNG: '/staff-busy.png',
  YUANGONG_STAFF_BUSY_SVG: '/staff-busy.svg',
  YUANGONG_FALLBACK_DESK: '/fallback-desk.svg',
  YUANGONG_FALLBACK_STAFF: '/fallback-staff.svg',
  YUANGONG_FALLBACK_STAFF_BUSY: '/fallback-staff-busy.svg',
}))

vi.mock('@/constants/yuangongEmployeeHotspots', () => ({
  YUANGONG_EMPLOYEE_HOTSPOTS: [
    { id: 'hs1', label: '数据库', routeName: 'database', leftPct: 10, topPct: 20, widthPct: 30, heightPct: 40 },
    { id: 'hs2', label: '订单', routeName: 'orders', leftPct: 50, topPct: 50, widthPct: 20, heightPct: 20, ariaLabel: '进入订单' },
  ],
}))

import YuangongInteractiveWorkstation from './YuangongInteractiveWorkstation.vue'

function mountComponent(propsOverrides: Record<string, unknown> = {}) {
  return mount(YuangongInteractiveWorkstation, {
    props: {
      statusLine: '在线',
      workflowFullName: '订单处理',
      enabled: false,
      busy: false,
      ...propsOverrides,
    },
  })
}

describe('YuangongInteractiveWorkstation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders the workstation container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.yiw').exists()).toBe(true)
  })

  it('renders title and lead text', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.yiw-title').text()).toContain('工位示意')
    expect(wrapper.find('.yiw-lead').exists()).toBe(true)
  })

  it('renders status ribbon with statusLine', () => {
    const wrapper = mountComponent({ statusLine: '忙碌中' })
    expect(wrapper.find('.yiw-ribbon--top .yiw-ribbon__v').text()).toBe('忙碌中')
  })

  it('renders workflow ribbon with workflowFullName', () => {
    const wrapper = mountComponent({ workflowFullName: '发货流程' })
    expect(wrapper.find('.yiw-ribbon--bottom .yiw-ribbon__v').text()).toBe('发货流程')
  })

  // --- primarySvg / primaryPng / fallbackFinal ---

  it('primarySvg returns desk SVG when not enabled', () => {
    const wrapper = mountComponent({ enabled: false })
    const vm = wrapper.vm as any
    expect(vm.sceneSrc).toBe('/desk.svg')
  })

  it('primarySvg returns staff SVG when enabled and not busy', () => {
    const wrapper = mountComponent({ enabled: true, busy: false })
    const vm = wrapper.vm as any
    expect(vm.sceneSrc).toBe('/staff.svg')
  })

  it('primarySvg returns staff-busy SVG when enabled and busy', () => {
    const wrapper = mountComponent({ enabled: true, busy: true })
    const vm = wrapper.vm as any
    expect(vm.sceneSrc).toBe('/staff-busy.svg')
  })

  // --- navigate ---

  it('navigate calls router.push with route name', async () => {
    const wrapper = mountComponent()
    const hotspotBtn = wrapper.findAll('.yiw-hit')[0]
    expect(hotspotBtn.exists()).toBe(true)
    await hotspotBtn.trigger('click')
    expect(mockPush).toHaveBeenCalledWith({ name: 'database' })
  })

  it('navigate calls router.push for second hotspot', async () => {
    const wrapper = mountComponent()
    const hotspotBtn = wrapper.findAll('.yiw-hit')[1]
    await hotspotBtn.trigger('click')
    expect(mockPush).toHaveBeenCalledWith({ name: 'orders' })
  })

  // --- onSceneError ---

  it('onSceneError falls back from SVG to PNG', async () => {
    const wrapper = mountComponent({ enabled: true, busy: false })
    const vm = wrapper.vm as any
    // Initial src is staff.svg
    expect(vm.sceneSrc).toBe('/staff.svg')
    // Trigger error on img
    await wrapper.find('.yiw-img').trigger('error')
    expect(vm.sceneSrc).toBe('/staff.png')
  })

  it('onSceneError falls back from PNG to fallback', async () => {
    const wrapper = mountComponent({ enabled: true, busy: false })
    const vm = wrapper.vm as any
    // First error: svg → png
    await wrapper.find('.yiw-img').trigger('error')
    expect(vm.sceneSrc).toBe('/staff.png')
    // Second error: png → fallback
    await wrapper.find('.yiw-img').trigger('error')
    expect(vm.sceneSrc).toBe('/fallback-staff.svg')
  })

  it('onSceneError falls back to desk fallback when not enabled', async () => {
    const wrapper = mountComponent({ enabled: false })
    const vm = wrapper.vm as any
    expect(vm.sceneSrc).toBe('/desk.svg')
    await wrapper.find('.yiw-img').trigger('error')
    expect(vm.sceneSrc).toBe('/desk.png')
    await wrapper.find('.yiw-img').trigger('error')
    expect(vm.sceneSrc).toBe('/fallback-desk.svg')
  })

  it('onSceneError falls back to staff-busy fallback when enabled and busy', async () => {
    const wrapper = mountComponent({ enabled: true, busy: true })
    const vm = wrapper.vm as any
    expect(vm.sceneSrc).toBe('/staff-busy.svg')
    await wrapper.find('.yiw-img').trigger('error')
    expect(vm.sceneSrc).toBe('/staff-busy.png')
    await wrapper.find('.yiw-img').trigger('error')
    expect(vm.sceneSrc).toBe('/fallback-staff-busy.svg')
  })

  // --- watch ---

  it('watch updates sceneSrc when enabled changes', async () => {
    const wrapper = mountComponent({ enabled: false })
    const vm = wrapper.vm as any
    expect(vm.sceneSrc).toBe('/desk.svg')
    await wrapper.setProps({ enabled: true })
    expect(vm.sceneSrc).toBe('/staff.svg')
  })

  it('watch updates sceneSrc when busy changes', async () => {
    const wrapper = mountComponent({ enabled: true, busy: false })
    const vm = wrapper.vm as any
    expect(vm.sceneSrc).toBe('/staff.svg')
    await wrapper.setProps({ busy: true })
    expect(vm.sceneSrc).toBe('/staff-busy.svg')
  })

  // --- frame classes ---

  it('applies yiw-frame--idle when not enabled', () => {
    const wrapper = mountComponent({ enabled: false })
    expect(wrapper.find('.yiw-frame').classes()).toContain('yiw-frame--idle')
  })

  it('applies yiw-frame--busy when enabled and busy', () => {
    const wrapper = mountComponent({ enabled: true, busy: true })
    expect(wrapper.find('.yiw-frame').classes()).toContain('yiw-frame--busy')
  })

  it('applies yiw-img--bob when enabled and busy', () => {
    const wrapper = mountComponent({ enabled: true, busy: true })
    expect(wrapper.find('.yiw-img').classes()).toContain('yiw-img--bob')
  })

  // --- hotspot rendering ---

  it('renders all hotspots from YUANGONG_EMPLOYEE_HOTSPOTS', () => {
    const wrapper = mountComponent()
    const hotspots = wrapper.findAll('.yiw-hit')
    expect(hotspots.length).toBe(2)
  })

  it('hotspot uses ariaLabel when provided', () => {
    const wrapper = mountComponent()
    const hotspots = wrapper.findAll('.yiw-hit')
    expect(hotspots[1].attributes('aria-label')).toBe('进入订单')
  })

  it('hotspot falls back to label when ariaLabel is not provided', () => {
    const wrapper = mountComponent()
    const hotspots = wrapper.findAll('.yiw-hit')
    expect(hotspots[0].attributes('aria-label')).toBe('数据库')
  })
})
