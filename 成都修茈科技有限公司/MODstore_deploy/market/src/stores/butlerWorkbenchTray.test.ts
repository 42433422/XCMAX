import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useButlerWorkbenchTrayStore } from './butlerWorkbenchTray'
import type { ButlerTrayAttachment } from './butlerWorkbenchTray'

function makeAttachment(id: string): ButlerTrayAttachment {
  return { id, name: `att-${id}`, status: 'ready' }
}

function makeGenerated(id: string) {
  return {
    id,
    filename: `gen-${id}.docx`,
    label: `Generated ${id}`,
    mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    url: `https://example.com/${id}`,
    source: 'office' as const,
    createdAt: 1,
  }
}

describe('useButlerWorkbenchTrayStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initializes with default empty state', () => {
    const store = useButlerWorkbenchTrayStore()
    expect(store.attachments).toEqual([])
    expect(store.generated).toEqual([])
    expect(store.maxVisible).toBe(3)
    expect(store.actions).toEqual({})
    expect(store.overflowCount).toBe(0)
    expect(store.hasTrayContent).toBe(false)
  })

  it('setWorkbenchFiles sets attachments only', () => {
    const store = useButlerWorkbenchTrayStore()
    const atts = [makeAttachment('1'), makeAttachment('2')]
    store.setWorkbenchFiles({ attachments: atts })
    expect(store.attachments).toEqual(atts)
    expect(store.generated).toEqual([])
  })

  it('setWorkbenchFiles sets generated only', () => {
    const store = useButlerWorkbenchTrayStore()
    const gens = [makeGenerated('g1')]
    store.setWorkbenchFiles({ generated: gens })
    expect(store.generated).toEqual(gens)
    expect(store.attachments).toEqual([])
  })

  it('setWorkbenchFiles sets maxVisible', () => {
    const store = useButlerWorkbenchTrayStore()
    store.setWorkbenchFiles({ maxVisible: 5 })
    expect(store.maxVisible).toBe(5)
  })

  it('setWorkbenchFiles ignores null maxVisible', () => {
    const store = useButlerWorkbenchTrayStore()
    store.setWorkbenchFiles({ maxVisible: 5 })
    store.setWorkbenchFiles({ maxVisible: null })
    expect(store.maxVisible).toBe(5)
  })

  it('setWorkbenchFiles ignores zero maxVisible (null check)', () => {
    const store = useButlerWorkbenchTrayStore()
    store.setWorkbenchFiles({ maxVisible: 0 })
    expect(store.maxVisible).toBe(0)
  })

  it('setWorkbenchFiles with empty payload does not change state', () => {
    const store = useButlerWorkbenchTrayStore()
    store.setWorkbenchFiles({ attachments: [makeAttachment('1')], maxVisible: 5 })
    store.setWorkbenchFiles({})
    expect(store.attachments).toHaveLength(1)
    expect(store.maxVisible).toBe(5)
  })

  it('registerActions merges actions', () => {
    const store = useButlerWorkbenchTrayStore()
    const remove = vi.fn()
    store.registerActions({ removeAttachment: remove })
    expect(store.actions.removeAttachment).toBe(remove)
    const download = vi.fn()
    store.registerActions({ downloadGenerated: download })
    expect(store.actions.removeAttachment).toBe(remove)
    expect(store.actions.downloadGenerated).toBe(download)
  })

  it('clearActions resets actions to empty', () => {
    const store = useButlerWorkbenchTrayStore()
    store.registerActions({ removeAttachment: vi.fn() })
    store.clearActions()
    expect(store.actions).toEqual({})
  })

  it('stripPlan computes correct counts for empty state', () => {
    const store = useButlerWorkbenchTrayStore()
    expect(store.stripPlan.stripAttachmentCount).toBe(0)
    expect(store.stripPlan.stripGeneratedCount).toBe(0)
    expect(store.stripPlan.overflowAttachmentCount).toBe(0)
    expect(store.stripPlan.overflowGeneratedCount).toBe(0)
    expect(store.stripPlan.overflowCount).toBe(0)
  })

  it('stripPlan computes overflow when attachments exceed cap', () => {
    const store = useButlerWorkbenchTrayStore()
    const atts = Array.from({ length: 7 }, (_, i) => makeAttachment(String(i + 1)))
    store.setWorkbenchFiles({ attachments: atts })
    expect(store.stripPlan.stripAttachmentCount).toBe(5)
    expect(store.stripPlan.overflowAttachmentCount).toBe(2)
  })

  it('stripPlan computes overflow when generated exceed cap', () => {
    const store = useButlerWorkbenchTrayStore()
    const gens = Array.from({ length: 5 }, (_, i) => makeGenerated(String(i + 1)))
    store.setWorkbenchFiles({ generated: gens })
    expect(store.stripPlan.stripGeneratedCount).toBe(3)
    expect(store.stripPlan.overflowGeneratedCount).toBe(2)
  })

  it('stripAttachments returns the visible slice', () => {
    const store = useButlerWorkbenchTrayStore()
    const atts = Array.from({ length: 7 }, (_, i) => makeAttachment(String(i + 1)))
    store.setWorkbenchFiles({ attachments: atts })
    expect(store.stripAttachments).toHaveLength(5)
    expect(store.stripAttachments[0].id).toBe('1')
  })

  it('overflowAttachments returns the overflow slice', () => {
    const store = useButlerWorkbenchTrayStore()
    const atts = Array.from({ length: 7 }, (_, i) => makeAttachment(String(i + 1)))
    store.setWorkbenchFiles({ attachments: atts })
    expect(store.overflowAttachments).toHaveLength(2)
    expect(store.overflowAttachments[0].id).toBe('6')
  })

  it('stripGenerated returns the visible slice of generated', () => {
    const store = useButlerWorkbenchTrayStore()
    const gens = Array.from({ length: 5 }, (_, i) => makeGenerated(String(i + 1)))
    store.setWorkbenchFiles({ generated: gens })
    expect(store.stripGenerated).toHaveLength(3)
  })

  it('overflowGenerated returns the overflow slice of generated', () => {
    const store = useButlerWorkbenchTrayStore()
    const gens = Array.from({ length: 5 }, (_, i) => makeGenerated(String(i + 1)))
    store.setWorkbenchFiles({ generated: gens })
    expect(store.overflowGenerated).toHaveLength(2)
  })

  it('overflowCount sums attachment and generated overflow', () => {
    const store = useButlerWorkbenchTrayStore()
    const atts = Array.from({ length: 7 }, (_, i) => makeAttachment(String(i + 1)))
    const gens = Array.from({ length: 5 }, (_, i) => makeGenerated(String(i + 1)))
    store.setWorkbenchFiles({ attachments: atts, generated: gens })
    expect(store.overflowCount).toBe(4)
  })

  it('hasTrayContent is true when attachments exist', () => {
    const store = useButlerWorkbenchTrayStore()
    store.setWorkbenchFiles({ attachments: [makeAttachment('1')] })
    expect(store.hasTrayContent).toBe(true)
  })

  it('hasTrayContent is true when generated exist', () => {
    const store = useButlerWorkbenchTrayStore()
    store.setWorkbenchFiles({ generated: [makeGenerated('1')] })
    expect(store.hasTrayContent).toBe(true)
  })

  it('hasTrayContent is true when overflow exists', () => {
    const store = useButlerWorkbenchTrayStore()
    const atts = Array.from({ length: 7 }, (_, i) => makeAttachment(String(i + 1)))
    store.setWorkbenchFiles({ attachments: atts })
    expect(store.hasTrayContent).toBe(true)
  })

  it('hasTrayContent is false when everything is empty', () => {
    const store = useButlerWorkbenchTrayStore()
    expect(store.hasTrayContent).toBe(false)
  })

  it('respects custom maxVisible for generated strip', () => {
    const store = useButlerWorkbenchTrayStore()
    const gens = Array.from({ length: 5 }, (_, i) => makeGenerated(String(i + 1)))
    store.setWorkbenchFiles({ generated: gens, maxVisible: 2 })
    expect(store.stripPlan.stripGeneratedCount).toBe(2)
    expect(store.stripPlan.overflowGeneratedCount).toBe(3)
    expect(store.stripGenerated).toHaveLength(2)
    expect(store.overflowGenerated).toHaveLength(3)
  })
})
