import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import StitchStage from './StitchStage.vue'

vi.mock('@/composables/useYuangongDeskIntrinsicSize', () => ({
  useYuangongDeskIntrinsicSize: () => ({
    deskW: { value: 80 },
    deskH: { value: 58 },
    deskIntrinsicReady: { value: true },
  }),
}))

describe('StitchStage.vue', () => {
  it('mounts composed strip shell', () => {
    const wrapper = mount(StitchStage, {
      props: {
        desks: [] as never[],
        hotspots: [] as never[],
        placements: [] as never[],
      },
      global: {
        stubs: {
          YuangongStation: true,
        },
      },
    })
    expect(wrapper.find('.stitch-stage').exists()).toBe(true)
  })
})
