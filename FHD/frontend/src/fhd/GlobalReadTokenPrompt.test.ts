import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import GlobalReadTokenPrompt from '@/fhd/GlobalReadTokenPrompt.vue'

describe('GlobalReadTokenPrompt', () => {
  it('is inert after database password gates were removed', () => {
    const wrapper = mount(GlobalReadTokenPrompt)
    expect(wrapper.exists()).toBe(true)
    expect(document.querySelector('.fhd-read-gate-root')).toBeNull()
    expect(document.querySelector('.fhd-read-fab')).toBeNull()
  })
})
