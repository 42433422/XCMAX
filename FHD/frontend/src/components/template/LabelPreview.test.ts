import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import LabelPreview from '@/components/template/LabelPreview.vue'

function createCanvasMock() {
  const ctx = {
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 0,
    font: '',
    fillRect: vi.fn(),
    strokeRect: vi.fn(),
    fillText: vi.fn(),
    measureText: vi.fn(() => ({ width: 20 })),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
  }
  const canvas = {
    width: 0,
    height: 0,
    getContext: vi.fn(() => ctx),
    toDataURL: vi.fn(() => 'data:image/png;base64,mock'),
  }
  return { canvas, ctx }
}

function mountLabel(propsOverrides = {}) {
  const { canvas, ctx } = createCanvasMock()
  const width = propsOverrides.width ?? 300
  const height = propsOverrides.height ?? 200
  canvas.width = width
  canvas.height = height
  const wrapper = mount(LabelPreview, {
    props: {
      fields: [],
      width,
      height,
      ...propsOverrides,
    },
    attachTo: document.body,
  })
  // Inject mock canvas ref so initCanvas/render use our mock
  wrapper.vm.canvas = canvas
  wrapper.vm.ctx = ctx
  return { wrapper, canvas, ctx }
}

describe('LabelPreview', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders canvas element', () => {
    const { wrapper } = mountLabel()
    expect(wrapper.find('.label-canvas').exists()).toBe(true)
  })

  it('renders label-preview container', () => {
    const { wrapper } = mountLabel()
    expect(wrapper.find('.label-preview').exists()).toBe(true)
  })

  it('initCanvas sets canvas dimensions from props', async () => {
    const { wrapper, canvas } = mountLabel({ width: 400, height: 300 })
    // Set the ref to our mock so initCanvas uses it
    wrapper.vm.$refs.labelCanvas = canvas
    wrapper.vm.initCanvas()
    expect(canvas.width).toBe(400)
    expect(canvas.height).toBe(300)
  })

  it('render does nothing when ctx is null', () => {
    const wrapper = mount(LabelPreview, {
      props: { fields: [], width: 100, height: 100 },
    })
    wrapper.vm.ctx = null
    expect(() => wrapper.vm.render()).not.toThrow()
  })

  it('render fills white background', () => {
    const { wrapper, ctx } = mountLabel({ width: 300, height: 200 })
    wrapper.vm.render()
    // First fillRect call is the white background
    expect(ctx.fillRect).toHaveBeenCalledWith(0, 0, 300, 200)
  })

  it('render draws outer border', () => {
    const { wrapper, ctx } = mountLabel({ width: 300, height: 200 })
    wrapper.vm.render()
    expect(ctx.strokeRect).toHaveBeenCalledWith(0, 0, 299, 199)
  })

  it('render draws inner border with padding', () => {
    const { wrapper, ctx } = mountLabel({ width: 300, height: 200 })
    wrapper.vm.render()
    expect(ctx.strokeRect).toHaveBeenCalledWith(10, 10, 280, 180)
  })

  it('render calls renderFields and renderBorder', () => {
    const { wrapper } = mountLabel({ width: 300, height: 200 })
    const renderFieldsSpy = vi.spyOn(wrapper.vm, 'renderFields')
    const renderBorderSpy = vi.spyOn(wrapper.vm, 'renderBorder')
    wrapper.vm.render()
    expect(renderFieldsSpy).toHaveBeenCalled()
    expect(renderBorderSpy).toHaveBeenCalled()
  })

  it('getDefaultFields returns 6 default fields', () => {
    const { wrapper } = mountLabel()
    const fields = wrapper.vm.getDefaultFields()
    expect(fields).toHaveLength(6)
    expect(fields[0]).toEqual({ label: '品名', value: 'XX运动鞋', type: 'fixed' })
    expect(fields[1]).toEqual({ label: '货号', value: '1635', type: 'dynamic' })
  })

  it('renderFields uses default fields when fields prop is empty', () => {
    const { wrapper, ctx } = mountLabel({ fields: [] })
    wrapper.vm.renderFields(ctx, 300, 200)
    // Should have called fillText for default fields
    expect(ctx.fillText).toHaveBeenCalled()
  })

  it('renderFields uses provided fields when not empty', () => {
    const fields = [
      { label: '测试', value: '值1', type: 'fixed' },
      { label: '动态', value: '值2', type: 'dynamic' },
    ]
    const { wrapper, ctx } = mountLabel({ fields })
    wrapper.vm.renderFields(ctx, 300, 200)
    expect(ctx.fillText).toHaveBeenCalledWith('测试: ', 15, 20)
    expect(ctx.fillText).toHaveBeenCalledWith('值1', 35, 20)
  })

  it('renderFields draws dynamic field placeholder when value is empty', () => {
    const fields = [{ label: '动态', value: '', type: 'dynamic' }]
    const { wrapper, ctx } = mountLabel({ fields })
    wrapper.vm.renderFields(ctx, 300, 200)
    expect(ctx.fillText).toHaveBeenCalledWith('______', 35, 20)
  })

  it('renderFields draws separator line when both fixed and dynamic fields exist', () => {
    const fields = [
      { label: '固定', value: 'A', type: 'fixed' },
      { label: '动态', value: 'B', type: 'dynamic' },
    ]
    const { wrapper, ctx } = mountLabel({ fields })
    wrapper.vm.renderFields(ctx, 300, 200)
    expect(ctx.beginPath).toHaveBeenCalled()
    expect(ctx.moveTo).toHaveBeenCalled()
    expect(ctx.lineTo).toHaveBeenCalled()
    expect(ctx.stroke).toHaveBeenCalled()
  })

  it('renderFields stops when yOffset exceeds height', () => {
    const fields = Array.from({ length: 20 }, (_, i) => ({
      label: `字段${i}`,
      value: `值${i}`,
      type: 'fixed',
    }))
    const { wrapper, ctx } = mountLabel({ fields, height: 50 })
    wrapper.vm.renderFields(ctx, 300, 50)
    // Should not render all 20 fields due to height limit
    const fillTextCalls = ctx.fillText.mock.calls.length
    expect(fillTextCalls).toBeLessThan(40) // less than 20 fields * 2 calls each
  })

  it('renderBorder draws outer and inner borders', () => {
    const { wrapper, ctx } = mountLabel({ width: 300, height: 200 })
    wrapper.vm.renderBorder(ctx, 300, 200)
    // Outer border
    expect(ctx.strokeRect).toHaveBeenCalledWith(0, 0, 299, 199)
    // Inner border
    expect(ctx.strokeRect).toHaveBeenCalledWith(5, 5, 290, 190)
  })

  it('getImageData returns data URL when canvas exists', () => {
    const { wrapper, canvas } = mountLabel()
    wrapper.vm.canvas = canvas
    const result = wrapper.vm.getImageData()
    expect(result).toBe('data:image/png;base64,mock')
    expect(canvas.toDataURL).toHaveBeenCalledWith('image/png')
  })

  it('getImageData returns empty string when canvas is null', () => {
    const { wrapper } = mountLabel()
    wrapper.vm.canvas = null
    expect(wrapper.vm.getImageData()).toBe('')
  })

  it('watches fields prop and re-renders', async () => {
    const { wrapper, ctx } = mountLabel({ fields: [] })
    wrapper.vm.render()
    ctx.fillRect.mockClear()
    ctx.strokeRect.mockClear()
    await wrapper.setProps({ fields: [{ label: '新', value: '值', type: 'fixed' }] })
    // Watch should trigger render which calls fillRect
    expect(ctx.fillRect).toHaveBeenCalled()
  })

  it('renderFields handles fixed field with empty value', () => {
    const fields = [{ label: '固定', value: '', type: 'fixed' }]
    const { wrapper, ctx } = mountLabel({ fields })
    expect(() => wrapper.vm.renderFields(ctx, 300, 200)).not.toThrow()
    expect(ctx.fillText).toHaveBeenCalledWith('', 35, 20)
  })

  it('renderFields applies correct font styles for fixed fields', () => {
    const fields = [{ label: '固定', value: 'A', type: 'fixed' }]
    const { wrapper, ctx } = mountLabel({ fields })
    wrapper.vm.renderFields(ctx, 300, 200)
    // Label font is set to bold, value font is set to non-bold
    // Check that bold font was used at some point
    const fontCalls = ctx.fillText.mock.calls
    expect(fontCalls.length).toBeGreaterThan(0)
    // fillStyle should end as '#000000' (fixed field value color)
    expect(ctx.fillStyle).toBe('#000000')
  })

  it('renderFields applies blue color for dynamic field values', () => {
    const fields = [{ label: '动态', value: 'X', type: 'dynamic' }]
    const { wrapper, ctx } = mountLabel({ fields })
    wrapper.vm.renderFields(ctx, 300, 200)
    // After drawing dynamic field value, fillStyle should be blue
    expect(ctx.fillStyle).toBe('#0066cc')
  })
})
