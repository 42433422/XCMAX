import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import PixelOfficeScene from './PixelOfficeScene.vue'

const engine = vi.hoisted(() => ({ stop: vi.fn(), start: vi.fn(), instances: 0, visibility: null as ((entries: any[]) => void) | null }))
vi.mock('@/utils/pixelOffice', () => ({
  TILE_SIZE: 16, loadOfficeAssets: async () => {}, renderFrame: vi.fn(), applyOfficeActivity: vi.fn(),
  buildOfficeLayout: (zones: any[], desks: any[]) => ({ layout: { cols: 6, rows: 6 }, rooms: zones.map(zone => ({ ...zone, col: 0, row: 0, width: 6, count: desks.length })), unassigned: [], seats: desks.map((row, i) => ({ empId: row.empId, id: i + 1, seatId: row.empId, col: 1, row: 2 })) }),
  startGameLoop: (...args: unknown[]) => { engine.start(...args); return { stop: engine.stop } },
  OfficeState: class {
    layout: any; characters = new Map(); seats = new Map(); tileMap = []; furniture = []; selectedAgentId: number | null = null
    constructor(layout: any) { this.layout = layout; engine.instances++ }
    addAgent(id: number) { this.characters.set(id, {}) }
    update() {} getCharacters() { return [...this.characters.values()] }
  },
}))
vi.mock('@/composables/useWorkflowEmployeeDesks', () => ({ resolveDeskStatusLine: (row: any) => row.snapshot.stage }))
const rows = (state: string) => [{ empId: 'a', shortName: '员工甲', panelTitle: '员工甲', enabled: true, snapshot: { stage: state, officeState: state } }] as any
const zones = [{ id: 'one', label: '信息技术部', color: '#333', employeeIds: ['a'] }]
let hidden = false
beforeEach(() => {
  engine.instances = 0; engine.stop.mockClear(); engine.start.mockClear(); hidden = false
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ imageSmoothingEnabled: false } as any)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('IntersectionObserver', class { constructor(callback: any) { engine.visibility = callback } observe() {} disconnect() {} })
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() } as any)
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); delete (document as any).hidden })

describe('office animation lifecycle', () => {
  it('keeps the renderer instance on live status updates and stops when the snapshot becomes stale', async () => {
    const wrapper = mount(PixelOfficeScene, { props: { desks: rows('working'), zones, selectedEmpId: 'a' } })
    await flushPromises(); expect(engine.start).toHaveBeenCalled(); const instances = engine.instances
    engine.start.mockClear(); engine.stop.mockClear()
    await wrapper.setProps({ desks: rows('offline') }); await flushPromises()
    expect(engine.instances).toBe(instances); expect(engine.stop).toHaveBeenCalled(); expect(engine.start).not.toHaveBeenCalled()
    expect(wrapper.get('[data-employee-id="a"]').attributes('data-office-state')).toBe('offline')
    await wrapper.get('[data-employee-id="a"]').trigger('click'); expect(wrapper.emitted('select')).toEqual([['a']]); wrapper.unmount()
  })
  it('pauses off-screen and when the page is hidden, resuming only when visible', async () => {
    const wrapper = mount(PixelOfficeScene, { props: { desks: rows('working'), zones, selectedEmpId: null } })
    await flushPromises(); engine.start.mockClear(); engine.stop.mockClear()
    engine.visibility?.([{ isIntersecting: false }]); expect(engine.stop).toHaveBeenCalled(); expect(engine.start).not.toHaveBeenCalled()
    hidden = true; engine.visibility?.([{ isIntersecting: true }]); expect(engine.start).not.toHaveBeenCalled()
    hidden = false; document.dispatchEvent(new Event('visibilitychange')); expect(engine.start).toHaveBeenCalledOnce()
    const stopped = engine.stop.mock.calls.length; wrapper.unmount(); expect(engine.stop.mock.calls.length).toBeGreaterThan(stopped)
  })
})
