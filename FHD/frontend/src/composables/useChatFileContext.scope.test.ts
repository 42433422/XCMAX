import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import chatApi from '@/api/chat'
import { useModsStore } from '@/stores/mods'
import { resolveChatIdentity } from '@/utils/chatStorageKeys'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { filesToMultimodalRows } from '@/utils/multimodalAttachments'
import { useChatExcelContext } from './useChatExcelContext'
import { useChatSessionHistory } from './useChatSessionHistory'
import { persistExcelAnalysisContext, readPersistedExcelAnalysisContext } from './useChatPersistence'

vi.mock('@/api/chat', () => ({ default: { getConversation: vi.fn() } }))
vi.mock('@/utils/multimodalAttachments', () => ({ filesToMultimodalRows: vi.fn() }))
enableAutoUnmount(afterEach)
const row = { kind: 'image' as const, filename: 'a.png', mime_type: 'image/png', data_url: 'data:image/png;base64,YQ==' }
const fileEvent = () => ({ target: { files: [new File(['a'], 'a.png')], value: 'a.png' } }) as unknown as Event
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r }); return { promise, resolve } }

function host() {
  const sessionId = ref('A'), addAndSaveMessage = vi.fn().mockResolvedValue(undefined)
  let files!: ReturnType<typeof useChatExcelContext>, history!: ReturnType<typeof useChatSessionHistory>
  const wrapper = mount(defineComponent({ setup() {
    const mods = useModsStore()
    files = useChatExcelContext({ sessionId, addAndSaveMessage, getIdentity: () => resolveChatIdentity(mods.activeModId) })
    history = useChatSessionHistory({
      sessionId, taskList: ref([]), activeTaskId: ref(''), expandedTaskIds: ref([]), taskFilter: ref('all'), currentTask: ref(null),
      lastExcelAnalysisContext: files.lastExcelAnalysisContext, linkedExcelSheet: files.linkedExcelSheet, linkedExcelAllSheets: files.linkedExcelAllSheets,
      loadMessages: vi.fn(), clearMessages: vi.fn(), persistTaskPanelStateForSession: vi.fn(), applyPersistedTaskPanelStateForSession: vi.fn(),
      clearPersistedTaskPanelState: vi.fn(), generateSessionId: () => 'new-session', normalizeServerContentToHtml: String,
    })
    return () => h('div')
  } }))
  return { files, history, sessionId, wrapper, addAndSaveMessage }
}

describe('chat file context ownership', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear(); sessionStorage.clear(); vi.clearAllMocks()
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    vi.mocked(chatApi.getConversation).mockResolvedValue({ success: true, messages: [] } as never)
    vi.mocked(filesToMultimodalRows).mockResolvedValue({ ok: true, rows: [row] })
  })
  afterEach(() => setRuntimeTenantStorageScopeInput(null))

  it('restores the selected conversation file and drops another conversation sheet/attachments', async () => {
    persistExcelAnalysisContext('A', { file_path: '/a.xlsx' })
    persistExcelAnalysisContext('B', { file_path: '/b.xlsx' })
    const test = host()
    expect(test.files.resolveExcelAnalysisContextForRequest()).toMatchObject({ file_path: '/a.xlsx' })
    test.files.linkedExcelSheet.value = { sheet_name: 'A sheet', sheet_index: 1 }
    test.files.linkedExcelAllSheets.value = true
    test.files.multimodalStaging.value = [row]
    await test.history.loadSession('B')
    const payload: Record<string, unknown> = {}
    test.files.injectExcelContextPayload(payload, [])
    test.files.consumeMultimodalIntoPlannerContext(payload, [])
    expect(payload.excel_file_path).toBe('/b.xlsx')
    expect(payload.excel_analysis_selected_sheet).toBeUndefined()
    expect(payload.multimodal_attachments).toBeUndefined()
    expect(test.files.linkedExcelAllSheets.value).toBe(false)
    await test.history.loadSession('A')
    expect(test.files.resolveExcelAnalysisContextForRequest()).toMatchObject({ file_path: '/a.xlsx' })
  })

  it('starts a clean conversation without erasing the previous conversation file cache', () => {
    persistExcelAnalysisContext('A', { file_path: '/a.xlsx' })
    const test = host()
    test.files.resolveExcelAnalysisContextForRequest()
    test.files.multimodalStaging.value = [row]
    test.history.newConversation()
    expect(test.files.resolveExcelAnalysisContextForRequest()).toBeNull()
    expect(test.files.multimodalStaging.value).toEqual([])
    expect(readPersistedExcelAnalysisContext('A')).toMatchObject({ file_path: '/a.xlsx' })
  })

  it.each(['session', 'owner', 'mod', 'unmount'])('discards a late attachment after %s changes', async kind => {
    const reading = deferred<Awaited<ReturnType<typeof filesToMultimodalRows>>>()
    vi.mocked(filesToMultimodalRows).mockReturnValue(reading.promise)
    const test = host()
    const pending = test.files.onMultimodalFileChange(fileEvent())
    if (kind === 'session') { test.sessionId.value = 'B'; test.sessionId.value = 'A' }
    if (kind === 'owner') setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 2 })
    if (kind === 'mod') useModsStore().activeModId = 'other-mod'
    if (kind === 'unmount') test.wrapper.unmount()
    reading.resolve({ ok: true, rows: [row] })
    await pending
    expect(test.files.multimodalStaging.value).toEqual([])
    expect(test.addAndSaveMessage).not.toHaveBeenCalled()
  })

  it('still accepts attachments for the live owner and conversation', async () => {
    const test = host()
    await test.files.onMultimodalFileChange(fileEvent())
    expect(test.files.multimodalPendingCount.value).toBe(1)
    expect(test.addAndSaveMessage).toHaveBeenCalledOnce()
  })
})
