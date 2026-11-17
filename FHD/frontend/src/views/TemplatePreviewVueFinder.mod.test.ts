import { describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { useTpVueFinder } from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/views/template-preview/useTpVueFinder'
import type { TemplatePreviewCtx } from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/views/template-preview/assemble'
import type { TplRecord } from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/views/template-preview/tpTemplateMeta'

vi.mock('@/components/template/vuefinder', () => ({ ArrayDriver: class {} }))

function setup() {
  const records = ref<TplRecord[]>([
    { id: 'first/id', name: '同名模板', category: 'excel' },
    { id: 'second', name: '同名模板', category: 'excel' },
  ])
  const previewTemplate = vi.fn()
  const finder = useTpVueFinder({
    exportScopedTemplates: records, getTemplateScopeLabel: () => '销售/出货', previewTemplate,
  } as unknown as TemplatePreviewCtx)
  return { records, previewTemplate, finder }
}

describe('template library record identity', () => {
  it('keeps duplicate display names independently selectable and previewable', () => {
    const { records, previewTemplate, finder } = setup()
    const files = finder.entries.value.filter(entry => entry.type === 'file')
    expect(files[0].basename).toBe(files[1].basename)
    expect(files[0].path).not.toBe(files[1].path)
    for (const [index, file] of files.entries()) {
      finder.onSelect([file])
      // The view passes this exact record to edit/replace/delete actions too.
      expect(finder.selectedTemplate.value?.id).toBe(records.value[index].id)
      const preventDefault = vi.fn()
      finder.onFileDclick({ item: file, preventDefault })
      expect(preventDefault).toHaveBeenCalledOnce()
      expect(previewTemplate).toHaveBeenLastCalledWith(records.value[index])
    }
  })

  it('refreshes selected data by ID after a rename and clears it after removal', async () => {
    const { records, finder } = setup()
    const file = finder.entries.value.find(entry => entry.type === 'file')!
    finder.onSelect([file])
    records.value = [{ ...records.value[0], name: '重命名', filename: 'new.xlsx' }, records.value[1]]
    await nextTick()
    expect(finder.entries.value.find(entry => entry.path === file.path)?.basename).toBe('重命名.xlsx')
    expect(finder.selectedTemplate.value).toEqual(records.value[0])
    records.value = [records.value[1]]
    await nextTick()
    expect(finder.selectedTemplate.value).toBeNull()
    finder.onSelect([file])
    expect(finder.selectedTemplate.value).toBeNull()
    finder.onSelect([])
    expect(finder.selectedTemplate.value).toBeNull()
  })
})
