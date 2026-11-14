import { ref } from 'vue'
import templatePreviewApi from '@/api/templatePreview'
import { appAlert } from '@/utils/appDialog'
import type { ExtractGridResponse } from './tpApiContracts'

/** Excel 网格映射工具（对应原视图 gridTool 相关状态与方法） */
export function useTpGridTool() {
  const gridToolFile = ref<File | null>(null)
  const gridToolResult = ref<ExtractGridResponse | null>(null)
  const extractingGrid = ref(false)
  const showGridToolModal = ref(false)

  function onGridToolFileSelected(event: Event) {
    const input = event?.target as HTMLInputElement | null
    const file = input?.files?.[0]
    if (!input || !file) return
    input.value = ''
    if (!extractingGrid.value) gridToolFile.value = file
  }

  async function extractGridFromExcel() {
    if (extractingGrid.value) return
    if (!gridToolFile.value) {
      await appAlert('请先选择 Excel 文件')
      return
    }
    extractingGrid.value = true
    try {
      const formData = new FormData()
      formData.append('file', gridToolFile.value)
      const res = (await templatePreviewApi.extractGrid(formData)) as ExtractGridResponse
      if (!res?.success) {
        throw new Error(res?.message || '提取失败')
      }
      gridToolResult.value = res
      showGridToolModal.value = true
    } catch (err) {
      await appAlert('网格提取失败：' + (err instanceof Error ? (err.message || '未知错误') : String(err)))
    } finally {
      extractingGrid.value = false
    }
  }

  function openGridToolPreview() {
    if (!gridToolResult.value) return
    showGridToolModal.value = true
  }

  return {
    gridToolFile,
    gridToolResult,
    extractingGrid,
    showGridToolModal,
    onGridToolFileSelected,
    extractGridFromExcel,
    openGridToolPreview,
  }
}
