import { describe, expect, it, vi } from 'vitest'
import { useChatAttachmentPicker } from './useChatAttachmentPicker'

describe('chat attachment picker', () => {
  it.each([
    ['26年销售明细.xlsx'],
    ['26年销售明细.xlsx', '汇总.xlsm'],
  ])('stages %j as composer attachments', async (...names) => {
    const attachments = {
      stageArtifactFiles: vi.fn(async () => names.length),
      stageMultimodalFiles: vi.fn(async () => {}),
      noteUnsupportedFiles: vi.fn(),
    }
    const picker = useChatAttachmentPicker(attachments, () => () => true)
    const workbooks = names.map((name) => new File(['sample'], name))
    const legacy = new File([], '历史.xls')
    const lockFile = new File([], '~$26年销售明细.xlsx')
    const batch = workbooks.length > 1
    const input = { files: batch ? [...workbooks, legacy, lockFile] : workbooks, value: 'selected' }
    const pending = picker.onAttachmentFileChange({ target: input } as unknown as Event)

    expect(picker.attachmentUploading.value).toBe(true)
    await pending
    expect(input.value).toBe('')
    expect(attachments.stageArtifactFiles).toHaveBeenCalledExactlyOnceWith(workbooks)
    if (batch) expect(attachments.noteUnsupportedFiles).toHaveBeenCalledExactlyOnceWith(['历史.xls'])
    else expect(attachments.noteUnsupportedFiles).not.toHaveBeenCalled()
    expect(attachments.stageMultimodalFiles).not.toHaveBeenCalled()
    expect(picker.attachmentUploading.value).toBe(false)
  })
})
