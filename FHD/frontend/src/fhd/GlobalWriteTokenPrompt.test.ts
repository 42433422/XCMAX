import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import GlobalWriteTokenPrompt from '@/fhd/GlobalWriteTokenPrompt.vue'

describe('GlobalWriteTokenPrompt', () => {
  it('is inert after database password gates were removed', () => {
    const wrapper = mount(GlobalWriteTokenPrompt)
    expect(wrapper.exists()).toBe(true)
    expect(document.querySelector('.fhd-write-gate-root')).toBeNull()
  })
})
