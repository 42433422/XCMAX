import { nextTick, ref, type Ref } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import templatePreviewApi from '@/api/templatePreview'
import type { TplRecord } from '../template-preview/tpTemplateMeta'
import type { TplDetailResponse } from '../template-preview/tpApiContracts'
import type { LeField, LeGrid } from './leTypes'
import { asRecord, labelCanvasSize, normalizeLabelFields, normalizeLabelGrid } from './leTemplateData'

export function useLeTemplate(deps: {
  route: RouteLocationNormalizedLoaded
  fields: Ref<LeField[]>
  grid: Ref<LeGrid | null>
  uploadedImage: Ref<string | null>
  canvasWidth: Ref<number>
  canvasHeight: Ref<number>
  templateName: Ref<string>
  drawCanvas: () => void
  clearSelection: () => void
}) {
  const loadingTemplate = ref(false)
  const templateLoadError = ref('')
  const templateReady = ref(false)
  const sourceTemplate = ref<TplRecord | null>(null)
  let loadSequence = 0

  async function loadTemplate() {
    const sequence = ++loadSequence
    loadingTemplate.value = true
    templateReady.value = false
    templateLoadError.value = ''
    sourceTemplate.value = null
    deps.fields.value = []
    deps.grid.value = null
    deps.uploadedImage.value = null
    deps.templateName.value = ''
    deps.clearSelection()
    try {
      const templateId = deps.route.query.templateId
      let template: TplRecord
      if (templateId != null) {
        if (typeof templateId !== 'string' || !templateId.trim()) throw new Error('模板标识无效，请返回模板列表重新打开。')
        const result = await templatePreviewApi.getTemplateDetail(templateId) as TplDetailResponse
        if (sequence !== loadSequence) return
        if (!result?.success || !result.template) throw new Error(result?.message || '模板加载失败，请重试。')
        template = JSON.parse(JSON.stringify(result.template)) as TplRecord
        if (String(template.id).replace(/^db:/, '') !== templateId.replace(/^db:/, '')) {
          throw new Error('返回的模板与所选模板不一致，请返回列表重试。')
        }
        if (template.category !== 'label') throw new Error('所选模板不是标签模板，请返回模板列表。')
        if (!String(template.name || '').trim()) throw new Error('模板缺少名称，请在模板列表修正后重试。')
      } else {
        const query = deps.route.query
        template = {
          id: '', category: 'label', name: typeof query.name === 'string' ? query.name : '新标签模板',
          fields: typeof query.fields === 'string' ? JSON.parse(query.fields) : [],
          preview_data: {
            grid: typeof query.grid === 'string' ? JSON.parse(query.grid) : null,
            image: typeof query.image === 'string' ? query.image : null,
          },
        }
      }
      const nextFields = normalizeLabelFields(template.fields)
      const preview = asRecord(template.preview_data)
      const nextGrid = normalizeLabelGrid(preview.grid)
      const size = labelCanvasSize(preview)
      deps.fields.value = nextFields
      deps.grid.value = nextGrid
      deps.canvasWidth.value = size.width
      deps.canvasHeight.value = size.height
      deps.uploadedImage.value = typeof preview.image === 'string' ? preview.image : null
      deps.templateName.value = template.name || ''
      sourceTemplate.value = templateId != null ? template : null
      templateReady.value = true
    } catch (error) {
      if (sequence !== loadSequence) return
      templateLoadError.value = error instanceof Error ? error.message : '模板加载失败，请重试。'
    } finally {
      if (sequence === loadSequence) {
        loadingTemplate.value = false
        await nextTick()
        deps.drawCanvas()
      }
    }
  }

  return { loadingTemplate, templateLoadError, templateReady, sourceTemplate, loadTemplate }
}
