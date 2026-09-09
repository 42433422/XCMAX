import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useTpTemplateList } from '../../../mods/xcagi-erp-domain-bridge/frontend/views/template-preview/useTpTemplateList'

const list = vi.hoisted(() => vi.fn())
vi.mock('@/api/templatePreview', () => ({ default: { listTemplates: list } }))

function pending() {
  let resolve!: (value: unknown) => void
  let reject!: (error: Error) => void
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

beforeEach(() => list.mockReset())

describe('template refresh ordering', () => {
  it('keeps the new request loading when an old request fails', async () => {
    const old = pending(), current = pending()
    list.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const state = useTpTemplateList()
    const first = state.refreshTemplates(), second = state.refreshTemplates()
    old.reject(new Error('old failure'))
    await first
    expect(state.loading.value).toBe(true)
    expect(state.error.value).toBeNull()
    current.resolve({ success: true, templates: [] })
    await second
    expect(state.loading.value).toBe(false)
  })

  it('does not replace a newer success with an older failure', async () => {
    const old = pending(), current = pending()
    list.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const state = useTpTemplateList()
    const first = state.refreshTemplates(), second = state.refreshTemplates()
    current.resolve({ success: true, templates: [] })
    await second
    old.reject(new Error('old failure'))
    await first
    expect(state.error.value).toBeNull()
    expect(state.loading.value).toBe(false)
  })
})
