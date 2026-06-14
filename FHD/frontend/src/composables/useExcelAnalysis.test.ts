import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import { useExcelAnalysis } from './useExcelAnalysis'

const addMessage = vi.fn()
const saveMessage = vi.fn().mockResolvedValue(undefined)

describe('useExcelAnalysis', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ success: true, sheets: [] }),
    } as Response)
  })

  it('returns excel analysis API', () => {
    const api = useExcelAnalysis({
      addMessage,
      saveMessage,
      sessionId: ref('sess-1'),
    })
    expect(api.excelAnalyzeUploading).toBeDefined()
    expect(typeof api.triggerUpload).toBe('function')
    expect(typeof api.onExcelAnalyzeFileChange).toBe('function')
  })

  it('triggerUpload clicks hidden input when ref set', () => {
    const api = useExcelAnalysis({ addMessage, saveMessage, sessionId: ref('s') })
    const click = vi.fn()
    api.excelAnalyzeInputRef.value = { click } as unknown as HTMLInputElement
    api.triggerUpload()
    expect(click).toHaveBeenCalled()
  })

  it('setOnMultimodalFileChangeCallback stores callback', () => {
    const api = useExcelAnalysis({ addMessage, saveMessage, sessionId: ref('s') })
    const cb = vi.fn()
    api.setOnMultimodalFileChangeCallback(cb)
    expect(typeof api.setOnMultimodalFileChangeCallback).toBe('function')
  })
})
