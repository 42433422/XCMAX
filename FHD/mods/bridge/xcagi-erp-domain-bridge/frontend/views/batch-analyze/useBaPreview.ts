import { ref } from 'vue'
import type { SheetGroup } from '@/stores/batchAnalyze'
import { appAlert } from '@/utils/appDialog'

// 预览弹窗数据（字段以 BaPreviewModal.vue 模板实际访问项为准）
interface PreviewField {
  label: string
  name: string
  type: string
}

interface PreviewData {
  fields: PreviewField[]
  preview_data: {
    sample_rows: Record<string, unknown>[]
    grid_preview: { rows: unknown[][] }
    sheet_name: string
    file_name: string
  }
  groupInfo: {
    name: string
    templateType: string
    matchScore: number
    sheetCount: number
    commonFieldsCount: number
    differenceFieldsCount: number
    diffGridRows: unknown[][]
  }
}

// 拆分自 BatchAnalyzeView.vue script（原第 518–521、600–676 行）；逻辑逐字迁移，行为不变。
export function useBaPreview() {
  const showPreviewModal = ref(false)
  const previewGroupName = ref('')
  const previewData = ref<PreviewData | null>(null)
  const previewLoading = ref(false)

  async function previewGroup(group: SheetGroup) {
    if (group.matchedSheets.length === 0) {
      await appAlert('该分组没有工作表')
      return
    }

    previewGroupName.value = group.name
    showPreviewModal.value = true
    previewLoading.value = true
    previewData.value = null

    try {
      const firstSheet = group.matchedSheets[0]
      const fields = group.commonFields.map((f) => ({
        label: f,
        name: f,
        type: 'dynamic'
      }))

      const sampleRows = firstSheet?.sampleRows || []

      const gridRows: unknown[][] = []
      if (sampleRows.length > 0) {
        const headers = Object.keys(sampleRows[0])
        gridRows.push(headers)
        for (const row of sampleRows.slice(0, 10)) {
          gridRows.push(headers.map(h => row[h] ?? ''))
        }
      }

      const diffGridRows: unknown[][] = []
      if (group.differenceFields.length > 0 && firstSheet?.sampleRows) {
        const diffHeaders = group.differenceFields
        const firstSheetFields = new Set(firstSheet.fields.map(f => f.toLowerCase()))
        const diffDataRows = firstSheet.sampleRows.slice(0, 5).map((row: Record<string, unknown>) => {
          const result: unknown[] = []
          for (const field of group.differenceFields) {
            const fieldLower = field.toLowerCase()
            if (firstSheetFields.has(fieldLower)) {
              result.push(row[field] ?? '')
            } else {
              result.push('-')
            }
          }
          return result
        })
        if (diffDataRows.length > 0) {
          diffGridRows.push(diffHeaders)
          diffGridRows.push(...diffDataRows)
        }
      }

      previewData.value = {
        fields,
        preview_data: {
          sample_rows: sampleRows,
          grid_preview: { rows: gridRows },
          sheet_name: firstSheet?.sheetName || '',
          file_name: firstSheet?.fileName || ''
        },
        groupInfo: {
          name: group.name,
          templateType: group.templateType,
          matchScore: group.matchScore,
          sheetCount: group.matchedSheets.length,
          commonFieldsCount: group.commonFields.length,
          differenceFieldsCount: group.differenceFields.length,
          diffGridRows
        }
      }
    } catch (e) {
      console.error('预览失败:', e)
      previewData.value = null
    } finally {
      previewLoading.value = false
    }
  }

  return { showPreviewModal, previewGroupName, previewData, previewLoading, previewGroup }
}
