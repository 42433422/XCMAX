import { describe, expect, it, beforeEach } from 'vitest'
import {
  readChatExportTemplatesRegistry,
  writeChatExportTemplatesRegistry,
  upsertChatExportTemplateEntry,
  removeChatExportTemplateEntry,
  isTemplateSyncedToChat,
  CHAT_EXPORT_TEMPLATES_REGISTRY_KEY,
  type ChatExportTemplateEntry,
} from './chatExportTemplatesRegistry'

const sample: ChatExportTemplateEntry = {
  kind: 'excel',
  id: 'tpl-1',
  displayName: '测试模板',
  business_scope: 'pricing',
  syncedAt: '2026-01-01T00:00:00.000Z',
}

describe('chatExportTemplatesRegistry', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('starts empty', () => {
    expect(readChatExportTemplatesRegistry()).toEqual([])
    expect(isTemplateSyncedToChat('tpl-1')).toBe(false)
  })

  it('upserts and reads entry', () => {
    upsertChatExportTemplateEntry(sample)
    const rows = readChatExportTemplatesRegistry()
    expect(rows).toHaveLength(1)
    expect(rows[0].id).toBe('tpl-1')
    expect(isTemplateSyncedToChat('tpl-1')).toBe(true)
  })

  it('removes entry', () => {
    upsertChatExportTemplateEntry(sample)
    removeChatExportTemplateEntry('tpl-1')
    expect(readChatExportTemplatesRegistry()).toEqual([])
  })

  it('write caps at 40 entries', () => {
    const many = Array.from({ length: 45 }, (_, i) => ({
      ...sample,
      id: `tpl-${i}`,
    }))
    writeChatExportTemplatesRegistry(many)
    expect(readChatExportTemplatesRegistry()).toHaveLength(40)
  })

  it('ignores invalid localStorage json', () => {
    localStorage.setItem(CHAT_EXPORT_TEMPLATES_REGISTRY_KEY, '{bad')
    expect(readChatExportTemplatesRegistry()).toEqual([])
  })
})
