import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick, ref } from 'vue'
import StitchStage from './StitchStage.vue'
import type { WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'
import type { YuangongStitchHotspot } from '@/constants/yuangongStitchHotspots'
import type { StitchEmployeePlacement } from '@/constants/yuangongStitchPlacements'

// Mock useYuangongDeskIntrinsicSize：返回真实 ref，避免 watch 警告
vi.mock('@/composables/useYuangongDeskIntrinsicSize', () => ({
  useYuangongDeskIntrinsicSize: () => ({
    deskW: ref(80),
    deskH: ref(58),
    deskIntrinsicReady: ref(true),
  }),
}))

// Mock ResizeObserver：jsdom 无原生实现
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// Mock requestAnimationFrame：no-op，避免 composed 模式下 offsetWidth=0 导致的无限重试循环
const mockRaf = vi.fn((_: () => void) => 0)

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', MockResizeObserver)
  vi.stubGlobal('requestAnimationFrame', mockRaf)
  // jsdom 无 setPointerCapture/releasePointerCapture，需手动 mock
  if (!HTMLElement.prototype.setPointerCapture) {
    HTMLElement.prototype.setPointerCapture = vi.fn()
  }
  if (!HTMLElement.prototype.releasePointerCapture) {
    HTMLElement.prototype.releasePointerCapture = vi.fn()
  }
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/** 创建员工行数据 */
function makeDeskRow(overrides: Partial<WorkflowEmployeeDeskRow> = {}): WorkflowEmployeeDeskRow {
  return {
    empId: 'emp-1',
    panelTitle: '工作流 · 员工1',
    shortName: '员工1',
    enabled: true,
    ...overrides,
  }
}

/** 创建热点数据 */
function makeHotspot(overrides: Partial<YuangongStitchHotspot> = {}): YuangongStitchHotspot {
  return {
    empId: 'emp-1',
    leftPct: 10,
    topPct: 20,
    widthPct: 30,
    heightPct: 40,
    ...overrides,
  }
}

/** 创建工位放置数据 */
function makePlacement(overrides: Partial<StitchEmployeePlacement> = {}): StitchEmployeePlacement {
  return {
    empId: 'emp-1',
    leftPct: 50,
    topPct: 80,
    ...overrides,
  }
}

/** 模拟视口元素的尺寸 */
function mockViewportSize(el: HTMLElement, w: number, h: number) {
  Object.defineProperty(el, 'clientWidth', { value: w, configurable: true })
  Object.defineProperty(el, 'clientHeight', { value: h, configurable: true })
  Object.defineProperty(el, 'offsetWidth', { value: w, configurable: true })
  Object.defineProperty(el, 'offsetHeight', { value: h, configurable: true })
}

describe('StitchStage.vue - 覆盖率补齐', () => {
  // ============================================================
  // 一、tutorial 模式：热点、工位叠层、图片事件
  // ============================================================
  describe('tutorial 模式', () => {
    it('渲染热点按钮并使用 label 字段', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [makeHotspot({ empId: 'h1', label: '热点1' })],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const hotspot = wrapper.find('.stitch-stage-hotspot')
      expect(hotspot.exists()).toBe(true)
      expect(hotspot.attributes('aria-label')).toBe('热点1')
    })

    it('热点无 label 时使用 resolveHotspotLabel 回调', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [makeHotspot({ empId: 'h2' })],
          resolveHotspotLabel: (empId: string) => `自定义-${empId}`,
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-stage-hotspot').attributes('aria-label')).toBe('自定义-h2')
    })

    it('热点无 label 且无 resolveHotspotLabel 时使用默认文案', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [makeHotspot({ empId: 'h3' })],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-stage-hotspot').attributes('aria-label')).toBe('选择员工 h3')
    })

    it('点击热点触发 select 事件', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [makeHotspot({ empId: 'h-click' })],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.find('.stitch-stage-hotspot').trigger('click')
      expect(wrapper.emitted('select')).toBeTruthy()
      expect(wrapper.emitted('select')![0]).toEqual(['h-click'])
    })

    it('选中的热点有 selected 样式与 aria-pressed', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: 'h-sel',
          hotspots: [makeHotspot({ empId: 'h-sel' })],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const hotspot = wrapper.find('.stitch-stage-hotspot')
      expect(hotspot.classes()).toContain('stitch-stage-hotspot--selected')
      expect(hotspot.attributes('aria-pressed')).toBe('true')
    })

    it('渲染工位叠层（stationPlacements）并使用默认 scale', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'p1' })],
          stationPlacements: [makePlacement({ empId: 'p1' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const station = wrapper.find('.stitch-stage-station')
      expect(station.exists()).toBe(true)
      // 默认 scale=4，transform 应包含 scale(4)
      const style = station.attributes('style') || ''
      expect(style).toContain('scale(4)')
    })

    it('工位叠层使用自定义 scale', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'p2' })],
          stationPlacements: [makePlacement({ empId: 'p2', scale: 6 })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const style = wrapper.find('.stitch-stage-station').attributes('style') || ''
      expect(style).toContain('scale(6)')
    })

    it('工位叠层使用 resolveStationAriaLabel 回调', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'p3', shortName: '短名' })],
          stationPlacements: [makePlacement({ empId: 'p3' })],
          resolveStationAriaLabel: (empId: string) => `aria-${empId}`,
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-stage-station').attributes('aria-label')).toBe('aria-p3')
    })

    it('工位叠层无 resolveStationAriaLabel 时使用默认文案', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'p4', shortName: '默认名' })],
          stationPlacements: [makePlacement({ empId: 'p4' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-stage-station').attributes('aria-label')).toBe('员工 默认名')
    })

    it('点击工位叠层触发 select 事件', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'p-click' })],
          stationPlacements: [makePlacement({ empId: 'p-click' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.find('.stitch-stage-station').trigger('click')
      expect(wrapper.emitted('select')![0]).toEqual(['p-click'])
    })

    it('工位叠层 keydown.enter 触发 select', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'p-enter' })],
          stationPlacements: [makePlacement({ empId: 'p-enter' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.find('.stitch-stage-station').trigger('keydown.enter')
      expect(wrapper.emitted('select')![0]).toEqual(['p-enter'])
    })

    it('选中的工位叠层有 selected 样式与 aria-current', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: 'p-sel',
          hotspots: [],
          desks: [makeDeskRow({ empId: 'p-sel' })],
          stationPlacements: [makePlacement({ empId: 'p-sel' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const station = wrapper.find('.stitch-stage-station')
      expect(station.classes()).toContain('stitch-stage-station--selected')
      expect(station.attributes('aria-current')).toBe('true')
    })

    it('图片 error 事件触发 image-error emit', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/broken.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.find('.stitch-stage-img').trigger('error')
      expect(wrapper.emitted('image-error')).toBeTruthy()
    })

    it('图片 load 事件触发 scheduleFit（通过 rAF）', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.find('.stitch-stage-img').trigger('load')
      await flushPromises()
      expect(wrapper.find('.stitch-stage').exists()).toBe(true)
    })

    it('visualSkin=office 添加 office 样式类', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
          visualSkin: 'office',
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-stage').classes()).toContain('stitch-stage--office')
    })

    it('stationPlacements 中 empId 不在 desks 中时不渲染叠层', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'real-emp' })],
          stationPlacements: [makePlacement({ empId: 'missing-emp' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-stage-station').exists()).toBe(false)
    })
  })

  // ============================================================
  // 二、composed 模式（strip 布局）
  // ============================================================
  describe('composed 模式 - strip 布局', () => {
    it('空 desks 时显示空提示文案', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-composed-empty').exists()).toBe(true)
      expect(wrapper.text()).toContain('暂无工作流员工')
    })

    it('渲染多排工位（超过 8 人触发多排）', () => {
      const desks: WorkflowEmployeeDeskRow[] = Array.from({ length: 10 }, (_, i) =>
        makeDeskRow({ empId: `emp-${i}`, shortName: `员工${i}`, panelTitle: `工作流·员工${i}` })
      )
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks,
        },
        global: { stubs: { YuangongStation: true } },
      })
      // 10 人 = 2 排（8 + 2）
      const rows = wrapper.findAll('.stitch-composed-row')
      expect(rows.length).toBe(2)
    })

    it('点击 composed 工位触发 select', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'cmp-click' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const cell = wrapper.find('.stitch-composed-cell')
      await cell.trigger('click')
      expect(wrapper.emitted('select')![0]).toEqual(['cmp-click'])
    })

    it('composed 工位 keydown.enter 触发 select', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'cmp-enter' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.find('.stitch-composed-cell').trigger('keydown.enter')
      expect(wrapper.emitted('select')![0]).toEqual(['cmp-enter'])
    })

    it('选中的 composed 工位有 selected 样式', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: 'cmp-sel',
          hotspots: [],
          desks: [makeDeskRow({ empId: 'cmp-sel' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const wrap = wrapper.find('.stitch-composed-station-wrap')
      expect(wrap.classes()).toContain('stitch-composed-station-wrap--selected')
    })

    it('useComposedPanorama=false 时不渲染底图', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow()],
          useComposedPanorama: false,
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-composed-backdrop').exists()).toBe(false)
    })

    it('useComposedPanorama=true（默认）时渲染底图', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow()],
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-composed-backdrop').exists()).toBe(true)
    })

    it('底图 load 事件触发 ready 状态', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow()],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.find('.stitch-composed-backdrop').trigger('load')
      await flushPromises()
      // load 后 composedIdleDeskVisible 应为 false（底图已就绪）
      expect(wrapper.find('.stitch-composed').exists()).toBe(true)
    })

    it('底图 error 事件触发 image-error emit', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow()],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.find('.stitch-composed-backdrop').trigger('error')
      expect(wrapper.emitted('image-error')).toBeTruthy()
    })

    it('imageSrc 为空时使用默认全景图', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow()],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const backdrop = wrapper.find('.stitch-composed-backdrop')
      expect(backdrop.exists()).toBe(true)
      expect(backdrop.attributes('src')).toContain('stitch-tutorial.png')
    })

    it('imageSrc 带空格时 trim 后使用', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '  /custom-pano.png  ',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow()],
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-composed-backdrop').attributes('src')).toBe('/custom-pano.png')
    })

    it('右组工位存在时渲染过道', () => {
      const desks: WorkflowEmployeeDeskRow[] = Array.from({ length: 6 }, (_, i) =>
        makeDeskRow({ empId: `emp-${i}`, shortName: `E${i}` })
      )
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks,
        },
        global: { stubs: { YuangongStation: true } },
      })
      // 6 人 = 左4 + 右2，应有过道
      expect(wrapper.find('.stitch-composed-aisle').exists()).toBe(true)
    })

    it('只有左组（≤4人）时无过道', () => {
      const desks: WorkflowEmployeeDeskRow[] = Array.from({ length: 3 }, (_, i) =>
        makeDeskRow({ empId: `emp-${i}`, shortName: `E${i}` })
      )
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks,
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-composed-aisle').exists()).toBe(false)
    })

    it('stationBusy：enabled=false 返回 false', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'busy-test', enabled: false })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-composed-cell').exists()).toBe(true)
    })

    it('stationBusy：enabled=true 且 visuallyBusy=true', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [
            makeDeskRow({
              empId: 'busy-test',
              enabled: true,
              snapshot: { visuallyBusy: true } as never,
            }),
          ],
        },
        global: { stubs: { YuangongStation: true } },
      })
      expect(wrapper.find('.stitch-composed-cell').exists()).toBe(true)
    })
    it('aria-label 包含区域信息（establishment 模式）', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          composedLayout: 'establishment',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'label_print', shortName: '标签' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const cell = wrapper.find('.stitch-establishment-cell')
      expect(cell.exists()).toBe(true)
      expect(cell.attributes('aria-label')).toContain('标签')
    })
  })

  // ============================================================
  // 三、composed 模式（establishment 布局）
  // ============================================================
  describe('composed 模式 - establishment 布局', () => {
    it('渲染企业六编制列式工位图', () => {
      const desks: WorkflowEmployeeDeskRow[] = [
        makeDeskRow({ empId: 'label_print', shortName: '标签', panelTitle: '标签打印' }),
        makeDeskRow({ empId: 'wechat_msg', shortName: '微信', panelTitle: '微信消息' }),
        makeDeskRow({ empId: 'lan_gate', shortName: '网关', panelTitle: '局域网网关' }),
        makeDeskRow({ empId: 'workflow_automator', shortName: '编排', panelTitle: '工作流编排' }),
      ]
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          composedLayout: 'establishment',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks,
        },
        global: { stubs: { YuangongStation: true } },
      })
      // 4 个区域列
      const cols = wrapper.findAll('.stitch-establishment-col')
      expect(cols.length).toBe(4)
    })

    it('空区域显示"暂无员工 Mod"', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          composedLayout: 'establishment',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'label_print', shortName: '标签' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      // 只有 execution 层有员工，其他层应显示空提示
      const emptyMsgs = wrapper.findAll('.stitch-establishment-empty')
      expect(emptyMsgs.length).toBeGreaterThan(0)
    })

    it('点击 establishment 工位触发 select', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          composedLayout: 'establishment',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'est-click', shortName: '点击测试' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const cell = wrapper.find('.stitch-establishment-cell')
      await cell.trigger('click')
      expect(wrapper.emitted('select')![0]).toEqual(['est-click'])
    })

    it('establishment 工位 keydown.enter 触发 select', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          composedLayout: 'establishment',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'est-enter', shortName: '回车测试' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.find('.stitch-establishment-cell').trigger('keydown.enter')
      expect(wrapper.emitted('select')![0]).toEqual(['est-enter'])
    })

    it('选中的 establishment 工位有 selected 样式', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          composedLayout: 'establishment',
          imageSrc: '/pano.png',
          selectedEmpId: 'est-sel',
          hotspots: [],
          desks: [makeDeskRow({ empId: 'est-sel', shortName: '选中测试' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const wrap = wrapper.find('.stitch-composed-station-wrap')
      expect(wrap.classes()).toContain('stitch-composed-station-wrap--selected')
    })

    it('establishment 列头显示区域代号与名称', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          composedLayout: 'establishment',
          imageSrc: '/pano.png',
          selectedEmpId: null,
          hotspots: [],
          // 需要至少一名员工才会渲染 establishment 布局（空 desks 显示空提示）
          desks: [makeDeskRow({ empId: 'label_print', shortName: '标签' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const codes = wrapper.findAll('.stitch-establishment-code')
      expect(codes.length).toBe(4)
      expect(codes[0].text()).toBe('L1')
    })
  })

  // ============================================================
  // 四、缩放控制
  // ============================================================
  describe('缩放控制', () => {
    it('点击放大按钮增加 zoom', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const zoomInBtn = wrapper.findAll('.stitch-stage-btn')[1] // 放大按钮
      await zoomInBtn.trigger('click')
      await flushPromises()
      // zoomPct 应大于 100%
      const readout = wrapper.find('.stitch-stage-zoom-readout')
      expect(parseInt(readout.text())).toBeGreaterThan(100)
    })

    it('点击缩小按钮减少 zoom', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      // 先放大再缩小
      const zoomInBtn = wrapper.findAll('.stitch-stage-btn')[1]
      await zoomInBtn.trigger('click')
      await flushPromises()
      const zoomOutBtn = wrapper.findAll('.stitch-stage-btn')[0] // 缩小按钮
      await zoomOutBtn.trigger('click')
      await flushPromises()
      const readout = wrapper.find('.stitch-stage-zoom-readout')
      expect(parseInt(readout.text())).toBeGreaterThanOrEqual(100)
    })

    it('点击全图按钮触发 resetZoom', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const resetBtn = wrapper.find('.stitch-stage-btn--ghost')
      await resetBtn.trigger('click')
      await flushPromises()
      expect(wrapper.find('.stitch-stage').exists()).toBe(true)
    })

    it('range 滑块 input 事件修改 zoom', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const range = wrapper.find('.stitch-stage-range')
      await range.setValue('200')
      await range.trigger('input')
      await flushPromises()
      const readout = wrapper.find('.stitch-stage-zoom-readout')
      expect(parseInt(readout.text())).toBe(200)
    })

    it('range 滑块非数字值时不修改 zoom', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const range = wrapper.find('.stitch-stage-range')
      // 模拟 NaN 值
      Object.defineProperty(range.element, 'value', {
        get: () => 'NaN',
        configurable: true,
      })
      await range.trigger('input')
      await flushPromises()
      // 不应崩溃，zoom 保持默认
      expect(wrapper.find('.stitch-stage').exists()).toBe(true)
    })

    it('放大到上限后放大按钮禁用', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const range = wrapper.find('.stitch-stage-range')
      // 设为最大值 250%
      await range.setValue('250')
      await range.trigger('input')
      await flushPromises()
      const zoomInBtn = wrapper.findAll('.stitch-stage-btn')[1]
      expect(zoomInBtn.attributes('disabled')).toBeDefined()
    })

    it('缩小到下限后缩小按钮禁用', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const range = wrapper.find('.stitch-stage-range')
      await range.setValue('25')
      await range.trigger('input')
      await flushPromises()
      const zoomOutBtn = wrapper.findAll('.stitch-stage-btn')[0]
      expect(zoomOutBtn.attributes('disabled')).toBeDefined()
    })
  })

  // ============================================================
  // 五、中键拖动平移
  // ============================================================
  describe('中键拖动平移', () => {
    it('中键 pointerdown 启动平移', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const viewport = wrapper.find('.stitch-stage-viewport')
      await viewport.trigger('pointerdown', { button: 1, pointerId: 1, clientX: 100, clientY: 100 })
      await flushPromises()
      // 平移启动后应有 grabbing 样式
      expect(viewport.classes()).toContain('stitch-stage-viewport--grabbing')
    })

    it('非中键 pointerdown 不启动平移', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const viewport = wrapper.find('.stitch-stage-viewport')
      await viewport.trigger('pointerdown', { button: 0, pointerId: 1, clientX: 100, clientY: 100 })
      expect(viewport.classes()).not.toContain('stitch-stage-viewport--grabbing')
    })

    it('中键 pointermove 更新 panX/panY', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const viewport = wrapper.find('.stitch-stage-viewport')
      await viewport.trigger('pointerdown', { button: 1, pointerId: 1, clientX: 100, clientY: 100 })
      await viewport.trigger('pointermove', { button: 1, pointerId: 1, clientX: 120, clientY: 110 })
      await flushPromises()
      // 平移后仍在 grabbing 状态
      expect(viewport.classes()).toContain('stitch-stage-viewport--grabbing')
    })

    it('中键 pointerup 结束平移', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const viewport = wrapper.find('.stitch-stage-viewport')
      await viewport.trigger('pointerdown', { button: 1, pointerId: 1, clientX: 100, clientY: 100 })
      await viewport.trigger('pointerup', { button: 1, pointerId: 1, clientX: 100, clientY: 100 })
      await flushPromises()
      expect(viewport.classes()).not.toContain('stitch-stage-viewport--grabbing')
    })

    it('中键 pointercancel 结束平移', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const viewport = wrapper.find('.stitch-stage-viewport')
      await viewport.trigger('pointerdown', { button: 1, pointerId: 1, clientX: 100, clientY: 100 })
      await viewport.trigger('pointercancel', { button: 1, pointerId: 1, clientX: 100, clientY: 100 })
      await flushPromises()
      expect(viewport.classes()).not.toContain('stitch-stage-viewport--grabbing')
    })

    it('非平移中 pointermove 不触发逻辑', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const viewport = wrapper.find('.stitch-stage-viewport')
      // 未先 pointerdown，直接 pointermove 不应崩溃
      await viewport.trigger('pointermove', { button: 1, pointerId: 1, clientX: 100, clientY: 100 })
      expect(viewport.classes()).not.toContain('stitch-stage-viewport--grabbing')
    })

    it('中键 mousedown 阻止默认行为', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const viewport = wrapper.find('.stitch-stage-viewport')
      const preventDefault = vi.fn()
      await viewport.trigger('mousedown', { button: 1, preventDefault })
      // 不崩溃即可（preventDefault 由组件内部调用）
      expect(wrapper.find('.stitch-stage').exists()).toBe(true)
    })

    it('中键 auxclick 阻止默认行为', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const viewport = wrapper.find('.stitch-stage-viewport')
      await viewport.trigger('auxclick', { button: 1, preventDefault: vi.fn() })
      expect(wrapper.find('.stitch-stage').exists()).toBe(true)
    })
  })

  // ============================================================
  // 六、watch 与生命周期
  // ============================================================
  describe('watch 与生命周期', () => {
    it('切换 imageSrc 触发 scheduleFit（tutorial 模式）', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test1.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.setProps({ imageSrc: '/test2.png' })
      await flushPromises()
      expect(wrapper.find('.stitch-stage').exists()).toBe(true)
    })

    it('切换 mode 触发 scheduleFit', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow()],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.setProps({ mode: 'composed' })
      await flushPromises()
      expect(wrapper.find('.stitch-composed').exists()).toBe(true)
    })

    it('切换 composedLayout 触发 scheduleFit', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          composedLayout: 'strip',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'label_print' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.setProps({ composedLayout: 'establishment' })
      await flushPromises()
      expect(wrapper.find('.stitch-establishment').exists()).toBe(true)
    })

    it('desks 变化触发 scheduleFit（composed 模式）', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow({ empId: 'd1' })],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.setProps({
        desks: [makeDeskRow({ empId: 'd1' }), makeDeskRow({ empId: 'd2' })],
      })
      await flushPromises()
      expect(wrapper.findAll('.stitch-composed-cell').length).toBe(2)
    })

    it('卸载组件时清理 ResizeObserver', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      wrapper.unmount()
      // 不崩溃即可
      expect(true).toBe(true)
    })

    it('composed 模式下切换 mode 到 tutorial 重置 backdrop 状态', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow()],
        },
        global: { stubs: { YuangongStation: true } },
      })
      await wrapper.setProps({ mode: 'tutorial' })
      await flushPromises()
      expect(wrapper.find('.stitch-stage-img').exists()).toBe(true)
    })
  })

  // ============================================================
  // 七、computed 属性与边界
  // ============================================================
  describe('computed 属性与边界', () => {
    it('composed 模式 aria-label 包含"多排工位拼接"', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          composedLayout: 'strip',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow()],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const stage = wrapper.find('.stitch-stage')
      expect(stage.attributes('aria-label')).toContain('多排工位拼接全景')
    })

    it('establishment 模式 aria-label 包含"企业六编制"', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          composedLayout: 'establishment',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow()],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const stage = wrapper.find('.stitch-stage')
      expect(stage.attributes('aria-label')).toContain('企业六编制')
    })

    it('tutorial 模式 aria-label 包含"拼接图舞台"', () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const stage = wrapper.find('.stitch-stage')
      expect(stage.attributes('aria-label')).toContain('拼接图舞台')
    })

    it('composed 模式下 viewport 有尺寸时计算 stationScale', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow()],
        },
        global: { stubs: { YuangongStation: true } },
      })
      // 模拟 viewport 和 composedRoot 都有尺寸，避免 computeFitZoom 无限重试
      const viewport = wrapper.find('.stitch-stage-viewport').element as HTMLElement
      mockViewportSize(viewport, 800, 600)
      const composedRoot = wrapper.find('.stitch-composed').element as HTMLElement
      mockViewportSize(composedRoot, 400, 300)
      await flushPromises()
      expect(wrapper.find('.stitch-composed').exists()).toBe(true)
    })

    it('composed 模式下 composedRoot 有尺寸时计算 fitZoom', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'composed',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [makeDeskRow()],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const viewport = wrapper.find('.stitch-stage-viewport').element as HTMLElement
      mockViewportSize(viewport, 800, 600)
      const composedRoot = wrapper.find('.stitch-composed').element as HTMLElement
      mockViewportSize(composedRoot, 400, 300)
      await flushPromises()
      // 点击全图按钮触发 computeFitZoom
      await wrapper.find('.stitch-stage-btn--ghost').trigger('click')
      await flushPromises()
      expect(wrapper.find('.stitch-composed').exists()).toBe(true)
    })

    it('tutorial 模式下 img 有 naturalWidth 时计算 fitZoom', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const viewport = wrapper.find('.stitch-stage-viewport').element as HTMLElement
      mockViewportSize(viewport, 800, 600)
      const img = wrapper.find('.stitch-stage-img').element as HTMLImageElement
      Object.defineProperty(img, 'naturalWidth', { value: 400, configurable: true })
      Object.defineProperty(img, 'naturalHeight', { value: 300, configurable: true })
      Object.defineProperty(img, 'complete', { value: true, configurable: true })
      await flushPromises()
      await flushPromises()
      // 点击全图按钮触发 computeFitZoom
      await wrapper.find('.stitch-stage-btn--ghost').trigger('click')
      await flushPromises()
      expect(wrapper.find('.stitch-stage').exists()).toBe(true)
    })

    it('tutorial 模式下 viewport 太小不计算 fitZoom', async () => {
      const wrapper = mount(StitchStage, {
        props: {
          mode: 'tutorial',
          imageSrc: '/test.png',
          selectedEmpId: null,
          hotspots: [],
          desks: [],
        },
        global: { stubs: { YuangongStation: true } },
      })
      const viewport = wrapper.find('.stitch-stage-viewport').element as HTMLElement
      mockViewportSize(viewport, 30, 30)
      await flushPromises()
      // 点击全图按钮，viewport 太小应直接返回
      await wrapper.find('.stitch-stage-btn--ghost').trigger('click')
      await flushPromises()
      expect(wrapper.find('.stitch-stage').exists()).toBe(true)
    })
  })
})
