import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useChatExcelContext } from './useChatExcelContext'
import { persistExcelAnalysisContext } from './useChatPersistence'
import type { MultimodalAttachmentRow } from '@/utils/multimodalAttachments'

function attachment(filename: string): MultimodalAttachmentRow {
  return {
    kind: 'image',
    filename,
    mime_type: 'image/png',
    data_url: 'data:image/png;base64,eA==',
  }
}

describe('chat session context isolation', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('does not leak attachments or Excel analysis across history and new-session switches', () => {
    const sessionId = ref('session-a')
    const ctx = useChatExcelContext({
      sessionId,
      addAndSaveMessage: vi.fn().mockResolvedValue(undefined),
    })
    const excelA = {
      file_path: '/tmp/a.xlsx',
      preview_data: { sheet_names: ['A表'] },
    }
    const excelB = {
      file_path: '/tmp/b.xlsx',
      preview_data: { sheet_names: ['B表'] },
    }
    persistExcelAnalysisContext('session-a', excelA)
    persistExcelAnalysisContext('session-b', excelB)
    ctx.activateSessionContext('session-a')
    ctx.multimodalStaging.value = [attachment('a.png')]

    sessionId.value = 'session-b'
    ctx.activateSessionContext('session-b')
    expect(ctx.multimodalStaging.value).toEqual([])
    expect(ctx.lastExcelAnalysisContext.value).toEqual(excelB)
    expect(ctx.linkedExcelSheet.value).toEqual({ sheet_name: 'B表', sheet_index: 1 })
    ctx.multimodalStaging.value = [attachment('b.png')]

    sessionId.value = 'session-a'
    ctx.activateSessionContext('session-a')
    expect(ctx.multimodalStaging.value.map((row) => row.filename)).toEqual(['a.png'])
    expect(ctx.lastExcelAnalysisContext.value).toEqual(excelA)
    expect(ctx.linkedExcelSheet.value).toEqual({ sheet_name: 'A表', sheet_index: 1 })

    sessionId.value = 'brand-new-session'
    ctx.clearSessionContext('brand-new-session', true)
    expect(ctx.multimodalStaging.value).toEqual([])
    expect(ctx.lastExcelAnalysisContext.value).toBeNull()
    expect(ctx.linkedExcelSheet.value).toBeNull()
  })

  it('retains a failed request snapshot and acknowledges only its exact rows after success', () => {
    const sessionId = ref('session-a')
    const ctx = useChatExcelContext({
      sessionId,
      addAndSaveMessage: vi.fn().mockResolvedValue(undefined),
    })
    const first = attachment('first.png')
    const addedWhileSending = attachment('added-while-sending.png')
    ctx.multimodalStaging.value = [first]
    const payload: Record<string, unknown> = {}
    const snapshot = ctx.consumeMultimodalIntoPlannerContext(payload, [])

    expect(snapshot?.rows).toEqual([first])
    expect(ctx.multimodalStaging.value).toEqual([first])
    ctx.multimodalStaging.value = [...ctx.multimodalStaging.value, addedWhileSending]

    // Network/timeout failure does not acknowledge the snapshot.
    expect(ctx.multimodalStaging.value).toEqual([first, addedWhileSending])

    // A later successful request removes only the rows that were actually sent.
    ctx.acknowledgeMultimodalRequest(snapshot)
    expect(ctx.multimodalStaging.value).toEqual([addedWhileSending])
  })
})
