import { ref } from 'vue'
import templatePreviewApi from '@/api/templatePreview'

// 拆分自 BatchAnalyzeView.vue script（原第 523、567–582 行）；逻辑逐字迁移，行为不变。
export function useBaTemplates() {
  const availableTemplates = ref<Array<{ id: string; name: string; templateType: string }>>([])

  async function loadTemplates() {
    try {
      const res = await templatePreviewApi.listTemplates()
      if (res?.success && Array.isArray(res.templates)) {
        availableTemplates.value = res.templates
          .filter((t: any) => t?.category === 'excel')
          .map((t: any) => ({
            id: t.id,
            name: t.name || t.template_name || '未命名模板',
            templateType: t.template_type || ''
          }))
      }
    } catch (e) {
      console.error('加载模板失败:', e)
    }
  }

  return { availableTemplates, loadTemplates }
}
