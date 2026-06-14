import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import LabelVisualEditor from './LabelVisualEditor.vue'

vi.mock('@/composables/useResizablePane', () => ({
  useResizablePane: () => ({
    paneStyle: {},
    isResizable: false,
    onResizeStart: vi.fn(),
    resetPaneSize: vi.fn(),
  }),
}))

describe('LabelVisualEditor.vue', () => {
  it('mounts editor layout', () => {
    const wrapper = mount(LabelVisualEditor, {
      props: {
        fields: [
          { id: 'f1', label: '品名', value: '测试', x: 10, y: 10, width: 100, height: 20 },
        ],
        canvasWidth: 400,
        canvasHeight: 300,
      },
      global: {
        stubs: { PaneResizeHandle: true },
      },
    })
    expect(wrapper.find('.visual-editor').exists()).toBe(true)
    expect(wrapper.text()).toContain('标签预览')
  })
})
