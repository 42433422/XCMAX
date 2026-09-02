import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useBatchAnalyzeStore } from '@/stores/batchAnalyze'
import templatePreviewApi from '@/api/templatePreview'
import { appAlert, appConfirm } from '@/utils/appDialog'

// 拆分自 BatchAnalyzeView.vue script（原第 683–755 行）；逻辑逐字迁移，行为不变。
export function useBaSave() {
  const store = useBatchAnalyzeStore()
  const { groups } = storeToRefs(store)

  const saveLoading = ref(false)
  const saveProgress = ref({ current: 0, total: 0, currentGroup: '' })

  async function saveAllTemplates() {
    if (groups.value.length === 0) {
      await appAlert('没有可保存的分组')
      return
    }

    const confirmed = await appConfirm(`确定要保存 ${groups.value.length} 个分组为模板吗？`)
    if (!confirmed) return

    saveLoading.value = true
    saveProgress.value = { current: 0, total: groups.value.length, currentGroup: '' }

    const results: { name: string; success: boolean; message: string }[] = []

    try {
      for (let i = 0; i < groups.value.length; i++) {
        const group = groups.value[i]
        saveProgress.value = { current: i + 1, total: groups.value.length, currentGroup: group.name }

        const templateName = group.recommendedTemplateName || `${group.templateType}模板_${i + 1}`
        const fields = group.commonFields.map((f) => ({
          label: f,
          name: f,
          type: 'dynamic'
        }))

        const firstSheet = group.matchedSheets[0]
        const sampleRows = firstSheet?.sampleRows || []

        const payload = {
          category: 'excel',
          template_type: group.templateType || 'Excel',
          business_scope: group.category || '',
          name: templateName,
          fields,
          preview_data: {
            sample_rows: sampleRows.slice(0, 10),
            grid_preview: { rows: [] },
            sheet_name: firstSheet?.sheetName || '',
            sheet_names: group.matchedSheets.map(s => s.sheetName),
            file_path: firstSheet?.fileName || ''
          },
          source: 'batch-analyze'
        }

        try {
          const res = await templatePreviewApi.createTemplateFromGrid(payload)
          if (res?.success) {
            results.push({ name: templateName, success: true, message: '保存成功' })
            if (group.recommendedTemplateId) {
              store.updateGroupTemplate(group.id, res.id || group.recommendedTemplateId, templateName, group.matchScore)
            }
          } else {
            results.push({ name: templateName, success: false, message: res?.message || '保存失败' })
          }
        } catch (e) {
          results.push({ name: templateName, success: false, message: e?.message || '未知错误' })
        }
      }

      const successCount = results.filter(r => r.success).length
      const failCount = results.filter(r => !r.success).length
      const message = `保存完成：成功 ${successCount} 个${failCount > 0 ? `，失败 ${failCount} 个` : ''}`
      await appAlert(message)

    } finally {
      saveLoading.value = false
      saveProgress.value = { current: 0, total: 0, currentGroup: '' }
    }
  }

  return { saveLoading, saveProgress, saveAllTemplates }
}
