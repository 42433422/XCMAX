import { ref } from 'vue'
import { isTemporaryDocument } from '@/utils/documentIntake'
import type { useChatExcelContext } from './useChatExcelContext'

type AttachmentContext = Pick<ReturnType<typeof useChatExcelContext>,
  'stageArtifactFiles' | 'stageMultimodalFiles' | 'noteUnsupportedFiles'>

export function useChatAttachmentPicker(
  attachments: AttachmentContext,
  captureIsCurrent: () => () => boolean,
) {
  const attachmentUploading = ref(false)

  async function onAttachmentFileChange(event: Event) {
    const input = event.target as HTMLInputElement
    const files = Array.from(input.files || []).filter((file) => !isTemporaryDocument(file.name))
    input.value = ''
    if (!files.length || attachmentUploading.value) return
    const isCurrent = captureIsCurrent()
    const workbooks = files.filter((file) => /\.(xlsx|xlsm)$/i.test(file.name))
    const legacy = files.filter((file) => /\.xls$/i.test(file.name))
    const other = files.filter((file) => !/\.(xlsx|xlsm|xls)$/i.test(file.name))
    attachmentUploading.value = true
    try {
      if (legacy.length) attachments.noteUnsupportedFiles(legacy.map((file) => file.name))
      if (workbooks.length) await attachments.stageArtifactFiles(workbooks)
      if (other.length && isCurrent()) await attachments.stageMultimodalFiles(other)
    } finally {
      attachmentUploading.value = false
    }
  }

  return { attachmentUploading, onAttachmentFileChange }
}
