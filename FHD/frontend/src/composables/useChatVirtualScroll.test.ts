import { describe, it, expect } from 'vitest'
import { ref } from 'vue'
import { useChatVirtualScroll } from './useChatVirtualScroll'

describe('useChatVirtualScroll', () => {
  it('renders all indices below threshold', () => {
    const messages = ref(Array.from({ length: 10 }, (_, i) => ({ role: 'ai' as const, content: `m${i}`, time: '' })))
    const scrollEl = ref<HTMLElement | null>(null)
    const vs = useChatVirtualScroll({
      messages,
      scrollEl,
      estimateHeight: () => 96,
      threshold: 50,
    })
    expect(vs.enabled.value).toBe(false)
    expect(vs.renderIndices.value).toHaveLength(10)
  })

  it('windows long lists', () => {
    const messages = ref(Array.from({ length: 80 }, (_, i) => ({ role: 'ai' as const, content: `m${i}`, time: '' })))
    const scrollEl = ref<HTMLElement | null>(null)
    const vs = useChatVirtualScroll({
      messages,
      scrollEl,
      estimateHeight: () => 96,
      threshold: 50,
    })
    expect(vs.enabled.value).toBe(true)
    expect(vs.renderIndices.value.length).toBeLessThan(80)
    expect(vs.renderIndices.value[0]).toBe(0)
  })
})
