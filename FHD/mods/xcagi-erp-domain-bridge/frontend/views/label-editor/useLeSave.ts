import type { Router } from 'vue-router'
import { computed, ref, type Ref } from 'vue'
import templatePreviewApi from '@/api/templatePreview'
import type { TplRecord } from '../template-preview/tpTemplateMeta'
import type { TplDetailResponse } from '../template-preview/tpApiContracts'
import type { LeField, LeGrid } from './leTypes'
import { asRecord, normalizeLabelFields } from './leTemplateData'
import { appAlert } from '@/utils/appDialog'
import { pushErpPage } from '@/utils/erpPagePaths'

export function useLeSave(deps: {
  fields: Ref<LeField[]>
  grid: Ref<LeGrid | null>
  uploadedImage: Ref<string | null>
  canvasWidth: Ref<number>
  canvasHeight: Ref<number>
  templateName: Ref<string>
  sourceTemplate: Ref<TplRecord | null>
  canSave: Ref<boolean>
  router: Router
}) {
  const savingTemplate = ref(false)
  const saveError = ref('')
  const saveName = computed(() => {
    const name = deps.templateName.value.trim()
    return deps.sourceTemplate.value?.name === name ? `${name}（副本）` : name
  })

  function normalizeFieldsForSave() {
    return normalizeLabelFields(deps.fields.value)
  }

  async function saveTemplate() {
    if (savingTemplate.value) return
    saveError.value = ''
    if (!deps.canSave.value) {
      saveError.value = '请先成功载入模板或完成识别，并添加有效字段后再保存。'
      return
    }
    if (!saveName.value) {
      saveError.value = '请输入模板名称。'
      return
    }
    savingTemplate.value = true
    try {
      const source = deps.sourceTemplate.value
      const res = await templatePreviewApi.createTemplate({
        name: saveName.value,
        category: 'label',
        template_type: source?.template_type || '标签',
        business_scope: source?.business_scope || '',
        fields: normalizeFieldsForSave(),
        preview_data: {
          ...source?.preview_data,
          grid: deps.grid.value,
          image_size: {
            ...asRecord(source?.preview_data?.image_size),
            width: deps.canvasWidth.value, height: deps.canvasHeight.value,
          },
          image: deps.uploadedImage.value,
        },
        file_path: source?.file_path || null,
        source: 'generated',
      }) as TplDetailResponse
      if (!res?.success || !res.template?.id) throw new Error(res?.message || '保存失败，未收到新模板标识。')
      await appAlert(`已保存新模板「${res.template.name || saveName.value}」${source ? '，原模板保持不变。' : '。'}`)
      window.dispatchEvent(new CustomEvent('xcagi:templates-updated', { detail: { source: 'label-editor', templateId: res.template.id } }))
      pushErpPage(deps.router, { path: returnPath() })
    } catch (err) {
      saveError.value = `模板保存失败：${err instanceof Error ? err.message : String(err)}。编辑内容已保留，可重试。`
    } finally {
      savingTemplate.value = false
    }
  }

  function goBack() {
    pushErpPage(deps.router, { path: returnPath() })
  }

  function returnPath() {
    return deps.router.currentRoute.value.query.returnTo === 'print' ? '/print' : '/template-preview'
  }

  return {
    normalizeFieldsForSave,
    saveTemplate,
    goBack,
    saveName, savingTemplate, saveError,
  }
}
