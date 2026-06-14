import { describe, it, expect } from 'vitest'

describe('ChatView.vue', () => {
  it('exports a Vue component module', async () => {
    const mod = await import('./ChatView.vue')
    expect(mod.default).toBeTruthy()
  })
})
