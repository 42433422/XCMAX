import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  supported: vi.fn(),
  upload: vi.fn(),
}))

vi.mock('@/api/core', () => ({ default: { post: mocks.post } }))
vi.mock('@/utils/officeEmployeeReadApi', () => ({
  isOfficeDockingFileSupported: mocks.supported,
  uploadChatOfficeFile: mocks.upload,
}))

import { useChatOfficeDocking } from './useChatOfficeDocking'

function createHarness() {
  const deps = {
    addAndSaveMessage: vi.fn().mockResolvedValue(undefined),
    stageExcelAnalysisContext: vi.fn(),
    sendDatabaseImportMessage: vi.fn().mockResolvedValue(undefined),
  }
  return { deps, docking: useChatOfficeDocking(deps) }
}

describe('useChatOfficeDocking ELT', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.supported.mockReturnValue(true)
    mocks.upload.mockImplementation(async (file: File) => ({
      file_path: `uploads/${file.name}`,
      workspace_root: '/workspace',
      filename: file.name,
    }))
  })

  it('parses through ELT, keeps the worksheet template optional, and queues approval on save', async () => {
    mocks.post
      .mockResolvedValueOnce({
        success: true,
        data: {
          pipeline: 'elt',
          summary: 'ELT 已解析',
          row_count: 2,
          headers: ['产品名称'],
          templates: [
            { id: '人员', label: '人员', sheet: '人员' },
            { id: '部门', label: '部门', sheet: '部门' },
          ],
          selected_template_index: -1,
        },
      })
      .mockResolvedValueOnce({
        success: true,
        data: { status: 'awaiting_approval', auto_ingest: { status: 'awaiting_approval', batch_id: 'aib-1' } },
      })
    const { deps, docking } = createHarness()
    const input = document.createElement('input')
    const file = new File(['x'], '宗南.xlsx')
    Object.defineProperty(input, 'files', { value: [file] })
    await docking.onOfficeDockingFileChange({ target: input } as unknown as Event)

    const item = docking.officeDockingReviewItems.value[0]
    expect(mocks.post.mock.calls[0][0]).toBe('/api/platform-shell/office/confirm')
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ intent: 'elt_parse', template_index: -1 })
    expect(mocks.post.mock.calls[0][2]).toBeUndefined()
    expect(item.selectedTemplateIndex).toBe(-1)
    expect(item.pipeline).toBe('elt')
    docking.pickOfficeWorksheetTemplate(item.id, 9)
    expect(item.selectedTemplateIndex).toBe(-1)
    docking.pickOfficeWorksheetTemplate(item.id, 0)
    expect(item.selectedTemplateIndex).toBe(0)
    await docking.confirmOfficeDockingReview()
    expect(mocks.post.mock.calls[1][1]).toMatchObject({ intent: 'elt_save', template_index: 0 })
    expect(mocks.post.mock.calls[1][2]).toBeUndefined()
    expect(item.commitStatus).toBe('committed')
    expect(deps.sendDatabaseImportMessage).not.toHaveBeenCalled()
    expect(deps.addAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('数据对接入库：宗南.xlsx'), 'ai')
  })
})
