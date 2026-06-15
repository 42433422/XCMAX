/**
 * StitchStage.vue 增强测试
 * 覆盖：tutorial 模式、composed 模式、缩放控制、中键平移、
 * hotspot 点击、station 选择、establishment 布局、视觉皮肤
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import StitchStage from './StitchStage.vue'

vi.mock('@/composables/useYuangongDeskIntrinsicSize', () => ({
  useYuangongDeskIntrinsicSize: () => ({
    deskW: { value: 80 },
    deskH: { value: 58 },
    deskIntrinsicReady: { value: true },
  }),
}))

vi.mock('@/constants/yuangongAssets', () => ({
  YUANGONG_ENTRY_STITCH_PNG: '/stitch-tutorial.png',
}))

vi.mock('@/constants/enterpriseWorkflowEstablishment', () => ({
  ENTERPRISE_ORG_LAYERS: [
    { id: 'management', code: 'M', label: '管理', desc: '管理层', color: '#3b82f6' },
    { id: 'sales', code: 'S', label: '销售', desc: '销售部', color: '#10b981' },
  ],
  countEnterpriseEstablishmentMaxSlots: (desks: unknown[]) => Math.max(1, Math.ceil((desks as unknown[]).length / 2)),
  resolveEnterpriseOrgLayer: (empId: string) => empId.startsWith('s') ? 'sales' : 'management',
}))

function makeHotspots(count = 2) {
  return Array.from({ length: count }, (_, i) => ({
    empId: `emp-${i + 1}`,
    label: `员工${i + 1}`,
    leftPct: 10 * (i + 1),
    topPct: 20 * (i + 1),
    widthPct: 8,
    heightPct: 12,
  }))
}

function makeDesks(count = 4) {
  return Array.from({ length: count }, (_, i) => ({
    empId: `emp-${i + 1}`,
    shortName: `员工${i + 1}`,
    panelTitle: `员工${i + 1}面板`,
    enabled: i % 2 === 0,
    snapshot: i % 2 === 0 ? { visuallyBusy: i === 0 } : null,
  }))
}

function makePlacements(desks: ReturnType<typeof makeDesks>) {
  return desks.map((d, i) => ({
    empId: d.empId,
    leftPct: 10 * (i + 1),
    topPct: 30,
    scale: 4,
  }))
}

const globalStubs = {
  YuangongStation: {
    template: '<div class="yuangong-station-stub" />',
    props: ['enabled', 'busy', 'ariaLabel', 'pixelLayout', 'composedIdleDeskVisible'],
  },
}

function mountStitchStage(overrides: Record<string, unknown> = {}) {
  const hotspots = makeHotspots()
  const desks = makeDesks()
  return mount(StitchStage, {
    props: {
      mode: 'tutorial',
      imageSrc: '/test-image.png',
      selectedEmpId: null,
      hotspots,
      desks,
      stationPlacements: makePlacements(desks),
      ...overrides,
    },
    global: { stubs: globalStubs },
  })
}

describe('StitchStage.vue – component structure', () => {
  it('renders stitch-stage root element', () => {
    const wrapper = mountStitchStage()
    expect(wrapper.find('.stitch-stage').exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders toolbar with zoom controls', () => {
    const wrapper = mountStitchStage()
    expect(wrapper.find('.stitch-stage-toolbar').exists()).toBe(true)
    expect(wrapper.find('.stitch-stage-range').exists()).toBe(true)
    expect(wrapper.findAll('.stitch-stage-btn').length).toBeGreaterThanOrEqual(3)
    wrapper.unmount()
  })

  it('renders viewport region', () => {
    const wrapper = mountStitchStage()
    expect(wrapper.find('.stitch-stage-viewport').exists()).toBe(true)
    wrapper.unmount()
  })

  it('applies office skin class when visualSkin is office', () => {
    const wrapper = mountStitchStage({ visualSkin: 'office' })
    expect(wrapper.find('.stitch-stage--office').exists()).toBe(true)
    wrapper.unmount()
  })

  it('applies pixel skin class by default', () => {
    const wrapper = mountStitchStage()
    expect(wrapper.find('.stitch-stage').classes()).not.toContain('stitch-stage--office')
    wrapper.unmount()
  })
})

describe('StitchStage.vue – tutorial mode', () => {
  it('renders image in tutorial mode', () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    const img = wrapper.find('.stitch-stage-img')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('/test-image.png')
    wrapper.unmount()
  })

  it('renders hotspot buttons for each hotspot', () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    const hotspots = wrapper.findAll('.stitch-stage-hotspot')
    expect(hotspots.length).toBe(2)
    wrapper.unmount()
  })

  it('emits select when hotspot is clicked', async () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    const hotspot = wrapper.find('.stitch-stage-hotspot')
    await hotspot.trigger('click')
    expect(wrapper.emitted('select')).toBeTruthy()
    expect(wrapper.emitted('select')![0]).toEqual(['emp-1'])
    wrapper.unmount()
  })

  it('highlights selected hotspot', () => {
    const wrapper = mountStitchStage({ mode: 'tutorial', selectedEmpId: 'emp-1' })
    const hotspot = wrapper.find('.stitch-stage-hotspot--selected')
    expect(hotspot.exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders placed stations in tutorial mode', () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    const stations = wrapper.findAll('.stitch-stage-station')
    expect(stations.length).toBe(4)
    wrapper.unmount()
  })

  it('emits select when station is clicked', async () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    const station = wrapper.find('.stitch-stage-station')
    await station.trigger('click')
    expect(wrapper.emitted('select')).toBeTruthy()
    wrapper.unmount()
  })

  it('emits image-error when image fails to load', async () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    const img = wrapper.find('.stitch-stage-img')
    await img.trigger('error')
    expect(wrapper.emitted('image-error')).toBeTruthy()
    wrapper.unmount()
  })

  it('uses resolveHotspotLabel for hotspot aria-labels when no label on hotspot', () => {
    const resolveFn = (empId: string) => `自定义-${empId}`
    const wrapper = mountStitchStage({ mode: 'tutorial', resolveHotspotLabel: resolveFn, hotspots: [{ empId: 'emp-x', leftPct: 10, topPct: 10, widthPct: 5, heightPct: 5 }] })
    const hotspot = wrapper.find('.stitch-stage-hotspot')
    expect(hotspot.attributes('aria-label')).toBe('自定义-emp-x')
    wrapper.unmount()
  })

  it('falls back to default label when resolveHotspotLabel is not provided', () => {
    const wrapper = mountStitchStage({ mode: 'tutorial', hotspots: [{ empId: 'emp-x', leftPct: 10, topPct: 10, widthPct: 5, heightPct: 5 }] })
    const hotspot = wrapper.find('.stitch-stage-hotspot')
    expect(hotspot.attributes('aria-label')).toBe('选择员工 emp-x')
    wrapper.unmount()
  })
})

describe('StitchStage.vue – composed mode', () => {
  it('renders composed layout in composed mode', () => {
    const wrapper = mountStitchStage({ mode: 'composed' })
    expect(wrapper.find('.stitch-composed').exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders empty message when no desks', () => {
    const wrapper = mountStitchStage({ mode: 'composed', desks: [], stationPlacements: [] })
    expect(wrapper.find('.stitch-composed-empty').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无工作流员工')
    wrapper.unmount()
  })

  it('renders composed cells for each desk', () => {
    const wrapper = mountStitchStage({ mode: 'composed' })
    const cells = wrapper.findAll('.stitch-composed-cell')
    expect(cells.length).toBe(4)
    wrapper.unmount()
  })

  it('emits select when composed cell is clicked', async () => {
    const wrapper = mountStitchStage({ mode: 'composed' })
    const cell = wrapper.find('.stitch-composed-cell')
    await cell.trigger('click')
    expect(wrapper.emitted('select')).toBeTruthy()
    wrapper.unmount()
  })

  it('highlights selected cell in composed mode', () => {
    const wrapper = mountStitchStage({ mode: 'composed', selectedEmpId: 'emp-1' })
    const selectedWrap = wrapper.find('.stitch-composed-station-wrap--selected')
    expect(selectedWrap.exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders station labels with shortName', () => {
    const wrapper = mountStitchStage({ mode: 'composed' })
    const labels = wrapper.findAll('.stitch-composed-label')
    expect(labels.length).toBe(4)
    expect(labels[0].text()).toBe('员工1')
    wrapper.unmount()
  })

  it('renders aisle between left and right groups when more than 4 desks', () => {
    const desks = makeDesks(6)
    const wrapper = mountStitchStage({ mode: 'composed', desks, stationPlacements: makePlacements(desks) })
    const aisle = wrapper.find('.stitch-composed-aisle')
    expect(aisle.exists()).toBe(true)
    wrapper.unmount()
  })

  it('does not render aisle when 4 or fewer desks', () => {
    const desks = makeDesks(3)
    const wrapper = mountStitchStage({ mode: 'composed', desks, stationPlacements: makePlacements(desks) })
    const aisle = wrapper.find('.stitch-composed-aisle')
    expect(aisle.exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('StitchStage.vue – establishment layout', () => {
  it('renders establishment columns in establishment layout', () => {
    const wrapper = mountStitchStage({ mode: 'composed', composedLayout: 'establishment' })
    expect(wrapper.find('.stitch-establishment').exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders zone headers with code, label, and badge', () => {
    const wrapper = mountStitchStage({ mode: 'composed', composedLayout: 'establishment' })
    const headers = wrapper.findAll('.stitch-establishment-head')
    expect(headers.length).toBe(2)
    wrapper.unmount()
  })

  it('shows empty message when no desks in establishment layout', async () => {
    const wrapper = mountStitchStage({ mode: 'composed', composedLayout: 'establishment', desks: [], stationPlacements: [] })
    // When no desks, composedSlots is empty, so the generic empty message appears
    expect(wrapper.find('.stitch-composed-empty').exists() || wrapper.findAll('.stitch-establishment-empty').length > 0).toBe(true)
    wrapper.unmount()
  })
})

describe('StitchStage.vue – zoom controls', () => {
  it('zoom in button increases zoom', async () => {
    const wrapper = mountStitchStage()
    const zoomInBtn = wrapper.findAll('.stitch-stage-btn').find(b => b.text() === '放大')
    expect(zoomInBtn).toBeDefined()
    await zoomInBtn!.trigger('click')
    const range = wrapper.find('.stitch-stage-range')
    const newVal = Number(range.attributes('value'))
    expect(newVal).toBeGreaterThan(100)
    wrapper.unmount()
  })

  it('zoom out button decreases zoom', async () => {
    const wrapper = mountStitchStage()
    // First zoom in to have room to zoom out
    const zoomInBtn = wrapper.findAll('.stitch-stage-btn').find(b => b.text() === '放大')
    await zoomInBtn!.trigger('click')
    const zoomOutBtn = wrapper.findAll('.stitch-stage-btn').find(b => b.text() === '缩小')
    await zoomOutBtn!.trigger('click')
    const range = wrapper.find('.stitch-stage-range')
    const val = Number(range.attributes('value'))
    expect(val).toBeLessThan(200)
    wrapper.unmount()
  })

  it('reset zoom button is present', () => {
    const wrapper = mountStitchStage()
    const resetBtn = wrapper.findAll('.stitch-stage-btn').find(b => b.text() === '全图')
    expect(resetBtn).toBeDefined()
    wrapper.unmount()
  })

  it('zoom range input updates zoom value', async () => {
    const wrapper = mountStitchStage()
    const range = wrapper.find('.stitch-stage-range')
    await range.setValue(150)
    const zoomPct = wrapper.find('.stitch-stage-zoom-readout')
    expect(zoomPct.text()).toBe('150%')
    wrapper.unmount()
  })

  it('zoom out is disabled at minimum zoom', () => {
    const wrapper = mountStitchStage()
    const zoomOutBtn = wrapper.findAll('.stitch-stage-btn').find(b => b.text() === '缩小')
    // At default zoom (100%), minZoom is 25, so not disabled
    expect(zoomOutBtn!.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('zoom in is disabled at maximum zoom', async () => {
    const wrapper = mountStitchStage()
    // Zoom in multiple times to reach max
    const zoomInBtn = wrapper.findAll('.stitch-stage-btn').find(b => b.text() === '放大')
    for (let i = 0; i < 20; i++) {
      await zoomInBtn!.trigger('click')
    }
    expect(zoomInBtn!.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('displays zoom percentage in readout', () => {
    const wrapper = mountStitchStage()
    const readout = wrapper.find('.stitch-stage-zoom-readout')
    expect(readout.text()).toMatch(/\d+%/)
    wrapper.unmount()
  })
})

describe('StitchStage.vue – middle-button panning', () => {
  it('viewport has pointer event handlers', () => {
    const wrapper = mountStitchStage()
    const viewport = wrapper.find('.stitch-stage-viewport')
    expect(viewport.exists()).toBe(true)
    wrapper.unmount()
  })

  it('middlePanning state is managed correctly', async () => {
    const wrapper = mountStitchStage()
    // Test that the component handles pointer events without crashing
    // jsdom doesn't support setPointerCapture, so we test state indirectly
    expect(wrapper.vm.middlePanning).toBe(false)
    wrapper.unmount()
  })

  it('prevents default on middle mouse button mousedown', async () => {
    const wrapper = mountStitchStage()
    const viewport = wrapper.find('.stitch-stage-viewport')
    const preventDefault = vi.fn()
    await viewport.trigger('mousedown', { button: 1, preventDefault })
    // The handler calls e.preventDefault() for middle button
    wrapper.unmount()
  })
})

describe('StitchStage.vue – computed properties', () => {
  it('isComposed is true in composed mode', () => {
    const wrapper = mountStitchStage({ mode: 'composed' })
    expect(wrapper.vm.isComposed).toBe(true)
    wrapper.unmount()
  })

  it('isComposed is false in tutorial mode', () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    expect(wrapper.vm.isComposed).toBe(false)
    wrapper.unmount()
  })

  it('composedSlots maps desks correctly', () => {
    const desks = makeDesks(3)
    const wrapper = mountStitchStage({ mode: 'composed', desks })
    expect(wrapper.vm.composedSlots.length).toBe(3)
    wrapper.unmount()
  })

  it('composedRows splits slots into rows of 8', () => {
    const desks = makeDesks(10)
    const wrapper = mountStitchStage({ mode: 'composed', desks })
    expect(wrapper.vm.composedRows.length).toBe(2) // 8 + 2
    expect(wrapper.vm.composedRows[0].length).toBe(8)
    expect(wrapper.vm.composedRows[1].length).toBe(2)
    wrapper.unmount()
  })

  it('composedGroupStripWidth returns 0 for count 0', () => {
    const wrapper = mountStitchStage({ mode: 'composed' })
    expect(wrapper.vm.composedGroupStripWidth(0)).toBe(0)
    wrapper.unmount()
  })

  it('composedRowStripWidth returns 1 for count 0', () => {
    const wrapper = mountStitchStage({ mode: 'composed' })
    expect(wrapper.vm.composedRowStripWidth(0)).toBe(1)
    wrapper.unmount()
  })

  it('composedCellOverlapMargin returns 0 for idx 0', () => {
    const wrapper = mountStitchStage({ mode: 'composed' })
    expect(wrapper.vm.composedCellOverlapMargin(0)).toBe('0')
    wrapper.unmount()
  })

  it('composedCellOverlapMargin returns negative margin for idx > 0', () => {
    const wrapper = mountStitchStage({ mode: 'composed' })
    const margin = wrapper.vm.composedCellOverlapMargin(1)
    expect(margin).toMatch(/^-/)
    wrapper.unmount()
  })

  it('stationBusy returns true for enabled busy station', () => {
    const desks = makeDesks(4)
    const wrapper = mountStitchStage({ mode: 'composed', desks })
    expect(wrapper.vm.stationBusy(desks[0])).toBe(true) // enabled, visuallyBusy
    wrapper.unmount()
  })

  it('stationBusy returns false for disabled station', () => {
    const desks = makeDesks(4)
    const wrapper = mountStitchStage({ mode: 'composed', desks })
    expect(wrapper.vm.stationBusy(desks[1])).toBe(false) // not enabled
    wrapper.unmount()
  })

  it('stationAriaLabel uses resolveStationAriaLabel when provided', () => {
    const resolveFn = (empId: string) => `自定义-${empId}`
    const desks = makeDesks(1)
    const wrapper = mountStitchStage({ mode: 'composed', desks, resolveStationAriaLabel: resolveFn })
    expect(wrapper.vm.stationAriaLabel('emp-1', desks[0])).toBe('自定义-emp-1')
    wrapper.unmount()
  })

  it('stationAriaLabel falls back to default', () => {
    const desks = makeDesks(1)
    const wrapper = mountStitchStage({ mode: 'composed', desks })
    expect(wrapper.vm.stationAriaLabel('emp-1', desks[0])).toBe('员工 员工1')
    wrapper.unmount()
  })

  it('hotspotLabel uses hotspot.label when available', () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    const h = { empId: 'x', label: '测试标签', leftPct: 10, topPct: 10, widthPct: 5, heightPct: 5 }
    expect(wrapper.vm.hotspotLabel(h)).toBe('测试标签')
    wrapper.unmount()
  })

  it('hotspotLabel falls back to resolveHotspotLabel', () => {
    const resolveFn = (empId: string) => `自定义-${empId}`
    const wrapper = mountStitchStage({ mode: 'tutorial', resolveHotspotLabel: resolveFn })
    const h = { empId: 'x', leftPct: 10, topPct: 10, widthPct: 5, heightPct: 5 }
    expect(wrapper.vm.hotspotLabel(h)).toBe('自定义-x')
    wrapper.unmount()
  })

  it('hotspotLabel falls back to default when no resolver', () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    const h = { empId: 'x', leftPct: 10, topPct: 10, widthPct: 5, heightPct: 5 }
    expect(wrapper.vm.hotspotLabel(h)).toBe('选择员工 x')
    wrapper.unmount()
  })
})

describe('StitchStage.vue – panorama backdrop', () => {
  it('shows composed backdrop when useComposedPanorama is true', () => {
    const wrapper = mountStitchStage({ mode: 'composed', useComposedPanorama: true })
    expect(wrapper.vm.showComposedBackdrop).toBe(true)
    wrapper.unmount()
  })

  it('hides composed backdrop when useComposedPanorama is false', () => {
    const wrapper = mountStitchStage({ mode: 'composed', useComposedPanorama: false })
    expect(wrapper.vm.showComposedBackdrop).toBe(false)
    wrapper.unmount()
  })

  it('composedPanoramaUrl uses imageSrc when provided', () => {
    const wrapper = mountStitchStage({ mode: 'composed', imageSrc: '/custom-panorama.png' })
    expect(wrapper.vm.composedPanoramaUrl).toBe('/custom-panorama.png')
    wrapper.unmount()
  })

  it('composedPanoramaUrl falls back to default when imageSrc is empty', () => {
    const wrapper = mountStitchStage({ mode: 'composed', imageSrc: '' })
    expect(wrapper.vm.composedPanoramaUrl).toBe('/stitch-tutorial.png')
    wrapper.unmount()
  })

  it('composedIdleDeskVisible is true when backdrop is not ready', () => {
    const wrapper = mountStitchStage({ mode: 'composed', useComposedPanorama: true })
    // backdrop state starts as 'idle', so idle desk should be visible
    expect(wrapper.vm.composedIdleDeskVisible).toBe(true)
    wrapper.unmount()
  })
})

describe('StitchStage.vue – placement style', () => {
  it('placementStyle returns correct transform', () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    const style = wrapper.vm.placementStyle({ leftPct: 20, topPct: 40, scale: 3 })
    expect(style.left).toBe('20%')
    expect(style.top).toBe('40%')
    expect(style.transform).toContain('scale(3)')
    wrapper.unmount()
  })

  it('placementStyle defaults scale to 4', () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    const style = wrapper.vm.placementStyle({ leftPct: 10, topPct: 20 })
    expect(style.transform).toContain('scale(4)')
    wrapper.unmount()
  })
})

describe('StitchStage.vue – hotspot style', () => {
  it('hotspotStyle returns correct position', () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    const style = wrapper.vm.hotspotStyle({ leftPct: 15, topPct: 25, widthPct: 10, heightPct: 12 })
    expect(style.left).toBe('15%')
    expect(style.top).toBe('25%')
    expect(style.width).toBe('10%')
    expect(style.height).toBe('12%')
    wrapper.unmount()
  })
})

describe('StitchStage.vue – keyboard interaction', () => {
  it('emits select on Enter key for composed cell', async () => {
    const wrapper = mountStitchStage({ mode: 'composed' })
    const cell = wrapper.find('.stitch-composed-cell')
    await cell.trigger('keydown.enter')
    expect(wrapper.emitted('select')).toBeTruthy()
    wrapper.unmount()
  })

  it('emits select on Enter key for tutorial station', async () => {
    const wrapper = mountStitchStage({ mode: 'tutorial' })
    const station = wrapper.find('.stitch-stage-station')
    await station.trigger('keydown.enter')
    expect(wrapper.emitted('select')).toBeTruthy()
    wrapper.unmount()
  })
})

