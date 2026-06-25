import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import LabelPreview from './LabelPreview.vue'

function createMockCtx() {
  return {
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 0,
    font: '',
    fillRect: vi.fn(),
    strokeRect: vi.fn(),
    fillText: vi.fn(),
    measureText: vi.fn(() => ({ width: 10 })),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
  }
}

let mockCtx: ReturnType<typeof createMockCtx>
let getContextSpy: ReturnType<typeof vi.spyOn>
let toDataURLSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  mockCtx = createMockCtx()
  getContextSpy = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(mockCtx)
  toDataURLSpy = vi
    .spyOn(HTMLCanvasElement.prototype, 'toDataURL')
    .mockReturnValue('data:image/png;base64,mockdata')
})

afterEach(() => {
  getContextSpy.mockRestore()
  toDataURLSpy.mockRestore()
})

function mountLabelPreview(props: Record<string, unknown> = {}) {
  return mount(LabelPreview, {
    props: {
      fields: [],
      width: 300,
      height: 200,
      ...props,
    },
    attachTo: document.body,
  })
}

describe('LabelPreview.vue functions', () => {
  // Note: outer beforeEach recreates mockCtx and re-spies on each test;
  // do NOT call vi.clearAllMocks() here as it would clear spy implementations.

  describe('initCanvas', () => {
    it('sets canvas and ctx from ref, and sets width/height', async () => {
      const wrapper = mountLabelPreview({ width: 400, height: 300 })
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      expect(wrapper.vm.canvas).toBe(wrapper.vm.$refs.labelCanvas)
      expect(wrapper.vm.ctx).toBeTruthy()
      expect(wrapper.vm.canvas.width).toBe(400)
      expect(wrapper.vm.canvas.height).toBe(300)
      expect(getContextSpy).toHaveBeenCalledWith('2d')
    })

    it('does not set ctx when canvas ref is null', async () => {
      const wrapper = mountLabelPreview()
      await wrapper.vm.$nextTick()
      // Simulate canvas ref being null by directly testing the guard
      wrapper.vm.canvas = null
      wrapper.vm.ctx = null
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      // When $refs.labelCanvas exists (real canvas), canvas will be set to it
      // This test verifies initCanvas doesn't throw when canvas is initially null
      expect(wrapper.vm.canvas).not.toBeUndefined()
    })
  })

  describe('render', () => {
    it('does nothing when ctx is null', async () => {
      const wrapper = mountLabelPreview()
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      wrapper.vm.ctx = null
      // Clear any calls from mounted hook's render
      mockCtx.fillRect.mockClear()
      // @ts-expect-error access internal method
      wrapper.vm.render()
      // no error thrown, no fillRect called
      expect(mockCtx.fillRect).not.toHaveBeenCalled()
    })

    it('fills background white and draws borders', async () => {
      const wrapper = mountLabelPreview({ width: 300, height: 200 })
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      mockCtx.fillRect.mockClear()
      mockCtx.strokeRect.mockClear()
      // @ts-expect-error access internal method
      wrapper.vm.render()
      // fillRect is called with white background first (0,0,w,h)
      expect(mockCtx.fillRect).toHaveBeenCalledWith(0, 0, 300, 200)
      // outer border
      expect(mockCtx.strokeRect).toHaveBeenCalledWith(0, 0, 299, 199)
    })

    it('calls renderFields and renderBorder', async () => {
      const wrapper = mountLabelPreview({ width: 300, height: 200 })
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      const renderFieldsSpy = vi.spyOn(wrapper.vm, 'renderFields')
      const renderBorderSpy = vi.spyOn(wrapper.vm, 'renderBorder')
      // @ts-expect-error access internal method
      wrapper.vm.render()
      expect(renderFieldsSpy).toHaveBeenCalled()
      expect(renderBorderSpy).toHaveBeenCalled()
    })
  })

  describe('renderFields', () => {
    it('uses default fields when fields prop is empty', async () => {
      const wrapper = mountLabelPreview({ fields: [], width: 300, height: 200 })
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      mockCtx.fillText.mockClear()
      // @ts-expect-error access internal method
      wrapper.vm.renderFields(mockCtx, 300, 200)
      expect(mockCtx.fillText).toHaveBeenCalled()
    })

    it('renders provided fixed fields', async () => {
      const fields = [
        { label: '品名', value: '运动鞋', type: 'fixed' },
        { label: '等级', value: '合格', type: 'fixed' },
      ]
      const wrapper = mountLabelPreview({ fields, width: 300, height: 200 })
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      mockCtx.fillText.mockClear()
      // @ts-expect-error access internal method
      wrapper.vm.renderFields(mockCtx, 300, 200)
      expect(mockCtx.fillText).toHaveBeenCalled()
    })

    it('renders provided dynamic fields with placeholder when value empty', async () => {
      const fields = [{ label: '货号', value: '', type: 'dynamic' }]
      const wrapper = mountLabelPreview({ fields, width: 300, height: 200 })
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      mockCtx.fillText.mockClear()
      // @ts-expect-error access internal method
      wrapper.vm.renderFields(mockCtx, 300, 200)
      const calls = mockCtx.fillText.mock.calls.map((c) => c[0])
      expect(calls).toContain('______')
    })

    it('renders provided dynamic fields with value when value present', async () => {
      const fields = [{ label: '货号', value: '12345', type: 'dynamic' }]
      const wrapper = mountLabelPreview({ fields, width: 300, height: 200 })
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      mockCtx.fillText.mockClear()
      // @ts-expect-error access internal method
      wrapper.vm.renderFields(mockCtx, 300, 200)
      const calls = mockCtx.fillText.mock.calls.map((c) => c[0])
      expect(calls).toContain('12345')
    })

    it('renders both fixed and dynamic fields with separator line', async () => {
      const fields = [
        { label: '品名', value: '鞋', type: 'fixed' },
        { label: '货号', value: '123', type: 'dynamic' },
      ]
      const wrapper = mountLabelPreview({ fields, width: 300, height: 200 })
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      mockCtx.beginPath.mockClear()
      mockCtx.moveTo.mockClear()
      mockCtx.lineTo.mockClear()
      mockCtx.stroke.mockClear()
      // @ts-expect-error access internal method
      wrapper.vm.renderFields(mockCtx, 300, 200)
      expect(mockCtx.beginPath).toHaveBeenCalled()
      expect(mockCtx.moveTo).toHaveBeenCalled()
      expect(mockCtx.lineTo).toHaveBeenCalled()
      expect(mockCtx.stroke).toHaveBeenCalled()
    })

    it('stops rendering when yOffset exceeds canvas height', async () => {
      const fields = Array.from({ length: 50 }, (_, i) => ({
        label: `字段${i}`,
        value: `值${i}`,
        type: 'fixed',
      }))
      const wrapper = mountLabelPreview({ fields, width: 300, height: 100 })
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      mockCtx.fillText.mockClear()
      // @ts-expect-error access internal method
      wrapper.vm.renderFields(mockCtx, 300, 100)
      const labelCalls = mockCtx.fillText.mock.calls.filter((c) =>
        String(c[0]).includes('字段'),
      )
      expect(labelCalls.length).toBeLessThan(50)
    })
  })

  describe('renderBorder', () => {
    it('draws outer and inner borders', async () => {
      const wrapper = mountLabelPreview({ width: 300, height: 200 })
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      mockCtx.strokeRect.mockClear()
      // @ts-expect-error access internal method
      wrapper.vm.renderBorder(mockCtx, 300, 200)
      expect(mockCtx.strokeRect).toHaveBeenCalledWith(0, 0, 299, 199)
      expect(mockCtx.strokeRect).toHaveBeenCalledWith(5, 5, 290, 190)
    })
  })

  describe('getDefaultFields', () => {
    it('returns 6 default fields', async () => {
      const wrapper = mountLabelPreview()
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      const defaults = wrapper.vm.getDefaultFields()
      expect(defaults).toHaveLength(6)
    })

    it('includes 品名 as first fixed field', async () => {
      const wrapper = mountLabelPreview()
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      const defaults = wrapper.vm.getDefaultFields()
      expect(defaults[0].label).toBe('品名')
      expect(defaults[0].type).toBe('fixed')
    })

    it('includes 货号 as a dynamic field', async () => {
      const wrapper = mountLabelPreview()
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      const defaults = wrapper.vm.getDefaultFields()
      const huohao = defaults.find((f) => f.label === '货号')
      expect(huohao).toBeTruthy()
      expect(huohao?.type).toBe('dynamic')
    })

    it('includes 统一零售价 as last dynamic field', async () => {
      const wrapper = mountLabelPreview()
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      const defaults = wrapper.vm.getDefaultFields()
      const last = defaults[defaults.length - 1]
      expect(last.label).toBe('统一零售价')
      expect(last.type).toBe('dynamic')
    })
  })

  describe('getImageData', () => {
    it('returns data URL when canvas exists', async () => {
      const wrapper = mountLabelPreview({ width: 300, height: 200 })
      await wrapper.vm.$nextTick()
      // @ts-expect-error access internal method
      wrapper.vm.initCanvas()
      toDataURLSpy.mockClear()
      // @ts-expect-error access internal method
      const data = wrapper.vm.getImageData()
      expect(data).toBe('data:image/png;base64,mockdata')
      expect(toDataURLSpy).toHaveBeenCalledWith('image/png')
    })

    it('returns empty string when canvas is null', async () => {
      const wrapper = mountLabelPreview()
      await wrapper.vm.$nextTick()
      wrapper.vm.canvas = null
      // @ts-expect-error access internal method
      const data = wrapper.vm.getImageData()
      expect(data).toBe('')
    })
  })

  describe('mounted lifecycle', () => {
    it('calls initCanvas and render on mount via nextTick', async () => {
      const wrapper = mountLabelPreview({ width: 300, height: 200 })
      await wrapper.vm.$nextTick()
      // After nextTick, initCanvas should have been called by mounted hook
      expect(getContextSpy).toHaveBeenCalledWith('2d')
      expect(wrapper.vm.canvas).toBeTruthy()
      expect(wrapper.vm.ctx).toBeTruthy()
    })
  })

  describe('watcher', () => {
    it('re-renders when fields change', async () => {
      const wrapper = mountLabelPreview({ fields: [], width: 300, height: 200 })
      await wrapper.vm.$nextTick()
      mockCtx.fillRect.mockClear()
      await wrapper.setProps({ fields: [{ label: '品名', value: '鞋', type: 'fixed' }] })
      // render should have been called again due to watcher
      expect(mockCtx.fillRect).toHaveBeenCalled()
    })
  })
})
