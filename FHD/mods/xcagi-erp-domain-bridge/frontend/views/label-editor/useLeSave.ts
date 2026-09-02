import type { Router } from 'vue-router'
import type { Ref } from 'vue'
import type { LeField } from './leTypes'
import { appAlert } from '@/utils/appDialog'
import { pushErpPage } from '@/utils/erpPagePaths'

// 拆分自 LabelEditorView.vue script（原 methods 中 normalizeFieldsForSave/saveTemplate/goBack）；
// 逻辑逐字迁移，行为不变。
export function useLeSave(deps: {
  fields: Ref<LeField[]>
  templateName: Ref<string>
  router: Router
}) {
  const { fields, templateName, router } = deps

  function normalizeFieldsForSave() {
    return (fields.value || []).map((field, idx) => ({
      id: field.id || idx + 1,
      label: field.label || `字段${idx + 1}`,
      value: field.value || '',
      type: field.type || 'dynamic',
      position: field.position || { left: 0, top: 0, width: 150, height: 30 }
    }))
  }

  async function saveTemplate() {
    const templateData = {
      name: templateName.value || '标签模板',
      category: 'label',
      template_type: '标签',
      fields: normalizeFieldsForSave(),
      source: 'generated'
    }

    try {
      const response = await fetch('/api/templates/create', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(templateData)
      })
      const res = (await response.json()) as { success?: boolean; message?: string }
      if (!res?.success) {
        throw new Error(res?.message || '保存失败')
      }
      await appAlert('模板保存成功！')
      window.dispatchEvent(new CustomEvent('xcagi:templates-updated', { detail: { source: 'label-editor' } }))
      pushErpPage(router, { name: 'template-preview' })
    } catch (err) {
      await appAlert(`模板保存失败：${err instanceof Error ? (err.message || '未知错误') : String(err)}`)
    }
  }

  function goBack() {
    pushErpPage(router, { path: '/template-preview', query: { scope: 'orders' } })
  }

  return {
    normalizeFieldsForSave,
    saveTemplate,
    goBack,
  }
}
