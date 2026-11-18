import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import LabelVisualEditor from './LabelVisualEditor.vue'

describe('LabelVisualEditor.vue', () => {
  it('mounts editor layout and paints its native canvas', async () => {
    const wrapper = mount(LabelVisualEditor, {
      props: {
        fields: [{ id: 'f1', label: '品名', value: '测试', type: 'fixed', position: { x: 10, y: 10, width: 100, height: 20 } }],
        canvasWidth: 400,
        canvasHeight: 300,
      },
      global: {
        stubs: { PaneResizeHandle: true },
      },
    })
    expect(wrapper.find('.visual-editor').exists()).toBe(true)
    expect(wrapper.text()).toContain('标签预览')
    await wrapper.vm.$nextTick()
    const canvas = wrapper.get<HTMLCanvasElement>('canvas').element
    expect(canvas.getContext('2d')!.getImageData(15, 15, 1, 1).data[3]).toBe(255)
    wrapper.unmount()
  })
})
