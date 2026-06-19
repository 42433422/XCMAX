import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import TemplateMediaPreview from '@/components/template/TemplateMediaPreview.vue'

function mountComponent(propsOverrides = {}) {
  return mount(TemplateMediaPreview, {
    props: {
      template: null,
      mediaKind: '',
      virtual: false,
      showExcelGrid: false,
      fields: [],
      sampleRows: [],
      gridData: null,
      excelTitle: 'Excel 预览',
      requiredTerms: [],
      displayName: '',
      statusHint: '',
      rows: 5,
      columns: 5,
      labelWidth: 280,
      labelHeight: 180,
      compact: false,
      ...propsOverrides,
    },
    global: {
      stubs: {
        ExcelPreview: {
          name: 'ExcelPreview',
          props: ['fields', 'sampleRows', 'title', 'gridData', 'rows', 'columns'],
          template: '<div class="excel-stub" />',
        },
        LabelPreview: {
          name: 'LabelPreview',
          props: ['fields', 'width', 'height'],
          template: '<div class="label-stub" />',
        },
      },
    },
  })
}

describe('TemplateMediaPreview.coverage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders root element', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.template-media-preview').exists()).toBe(true)
  })

  it('resolvedMediaKind returns mediaKind when valid excel', () => {
    const wrapper = mountComponent({ mediaKind: 'excel' })
    expect((wrapper.vm as any).resolvedMediaKind).toBe('excel')
  })

  it('resolvedMediaKind returns mediaKind when valid word', () => {
    const wrapper = mountComponent({ mediaKind: 'word' })
    expect((wrapper.vm as any).resolvedMediaKind).toBe('word')
  })

  it('resolvedMediaKind returns mediaKind when valid csv', () => {
    const wrapper = mountComponent({ mediaKind: 'csv' })
    expect((wrapper.vm as any).resolvedMediaKind).toBe('csv')
  })

  it('resolvedMediaKind returns mediaKind when valid ppt', () => {
    const wrapper = mountComponent({ mediaKind: 'ppt' })
    expect((wrapper.vm as any).resolvedMediaKind).toBe('ppt')
  })

  it('resolvedMediaKind returns mediaKind when valid pdf', () => {
    const wrapper = mountComponent({ mediaKind: 'pdf' })
    expect((wrapper.vm as any).resolvedMediaKind).toBe('pdf')
  })

  it('resolvedMediaKind falls back to label from template.category', () => {
    const wrapper = mountComponent({ mediaKind: '', template: { category: 'label' } })
    expect((wrapper.vm as any).resolvedMediaKind).toBe('label')
  })

  it('resolvedMediaKind normalizes template.category to excel fallback', () => {
    const wrapper = mountComponent({ mediaKind: '', template: { category: 'unknown' } })
    expect((wrapper.vm as any).resolvedMediaKind).toBe('excel')
  })

  it('resolvedMediaKind returns excel when no mediaKind and no template', () => {
    const wrapper = mountComponent({ mediaKind: '', template: null })
    expect((wrapper.vm as any).resolvedMediaKind).toBe('excel')
  })

  it('resolvedMediaKind trims whitespace in mediaKind', () => {
    const wrapper = mountComponent({ mediaKind: '  excel  ' })
    expect((wrapper.vm as any).resolvedMediaKind).toBe('excel')
  })

  it('resolvedMediaKind handles empty string mediaKind', () => {
    const wrapper = mountComponent({ mediaKind: '', template: { category: 'word' } })
    expect((wrapper.vm as any).resolvedMediaKind).toBe('word')
  })

  it('iconClass returns icon for resolved excel kind', () => {
    const wrapper = mountComponent({ mediaKind: 'excel' })
    expect((wrapper.vm as any).iconClass).toBe('fa-file-excel-o')
  })

  it('iconClass returns icon for resolved word kind', () => {
    const wrapper = mountComponent({ mediaKind: 'word' })
    expect((wrapper.vm as any).iconClass).toBe('fa-file-word-o')
  })

  it('iconClass returns icon for resolved pdf kind', () => {
    const wrapper = mountComponent({ mediaKind: 'pdf' })
    expect((wrapper.vm as any).iconClass).toBe('fa-file-pdf-o')
  })

  it('uploadHint returns hint string', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).uploadHint).toContain('Excel')
  })

  it('rootClass includes compact class when compact', () => {
    const wrapper = mountComponent({ compact: true })
    expect((wrapper.vm as any).rootClass['template-media-preview--compact']).toBe(true)
  })

  it('rootClass excludes compact class when not compact', () => {
    const wrapper = mountComponent({ compact: false })
    expect((wrapper.vm as any).rootClass['template-media-preview--compact']).toBe(false)
  })

  it('rootClass includes kind class for resolved kind', () => {
    const wrapper = mountComponent({ mediaKind: 'word' })
    expect((wrapper.vm as any).rootClass['template-media-preview--word']).toBe(true)
  })

  it('isVirtualPlaceholder is true when virtual and not excel grid and not label', () => {
    const wrapper = mountComponent({ virtual: true, mediaKind: 'excel' })
    expect((wrapper.vm as any).isVirtualPlaceholder).toBe(true)
  })

  it('isVirtualPlaceholder is false when not virtual', () => {
    const wrapper = mountComponent({ virtual: false, mediaKind: 'excel' })
    expect((wrapper.vm as any).isVirtualPlaceholder).toBe(false)
  })

  it('isVirtualPlaceholder is false when showExcelGrid true', () => {
    const wrapper = mountComponent({ virtual: true, showExcelGrid: true, mediaKind: 'excel' })
    expect((wrapper.vm as any).isVirtualPlaceholder).toBe(false)
  })

  it('isVirtualPlaceholder is false when resolvedMediaKind is label', () => {
    const wrapper = mountComponent({ virtual: true, mediaKind: '', template: { category: 'label' } })
    expect((wrapper.vm as any).isVirtualPlaceholder).toBe(false)
  })

  it('renders ExcelPreview when excel kind and showExcelGrid', () => {
    const wrapper = mountComponent({ mediaKind: 'excel', showExcelGrid: true })
    expect(wrapper.findComponent({ name: 'ExcelPreview' }).exists()).toBe(true)
  })

  it('renders virtual placeholder when virtual and no grid', () => {
    const wrapper = mountComponent({ virtual: true, mediaKind: 'excel' })
    expect(wrapper.find('.tp-card-placeholder').exists()).toBe(true)
    expect(wrapper.find('.tp-placeholder-title').text()).toContain('待上传模板')
  })

  it('virtual placeholder shows required terms when provided', () => {
    const wrapper = mountComponent({ virtual: true, mediaKind: 'excel', requiredTerms: ['品名', '规格'] })
    expect(wrapper.find('.tp-placeholder-terms').text()).toContain('品名')
    expect(wrapper.find('.tp-placeholder-terms').text()).toContain('规格')
  })

  it('virtual placeholder shows upload hint when no required terms', () => {
    const wrapper = mountComponent({ virtual: true, mediaKind: 'excel', requiredTerms: [] })
    expect(wrapper.find('.tp-placeholder-terms').text()).toContain('Excel')
  })

  it('renders LabelPreview when resolvedMediaKind is label', () => {
    const wrapper = mountComponent({ mediaKind: '', template: { category: 'label' } })
    expect(wrapper.findComponent({ name: 'LabelPreview' }).exists()).toBe(true)
  })

  it('renders file placeholder with icon for word kind', () => {
    const wrapper = mountComponent({ mediaKind: 'word', displayName: 'report.docx' })
    expect(wrapper.find('.tp-card-placeholder--word').exists()).toBe(true)
    expect(wrapper.find('.tmp-file-name').text()).toBe('report.docx')
  })

  it('renders status hint when provided', () => {
    const wrapper = mountComponent({ mediaKind: 'word', statusHint: '已解析' })
    expect(wrapper.find('.tmp-status').text()).toBe('已解析')
  })

  it('does not render status hint when empty', () => {
    const wrapper = mountComponent({ mediaKind: 'word', statusHint: '' })
    expect(wrapper.find('.tmp-status').exists()).toBe(false)
  })

  it('renders excel placeholder icon for excel kind without grid', () => {
    const wrapper = mountComponent({ mediaKind: 'excel', showExcelGrid: false })
    expect(wrapper.find('.tp-card-placeholder--excel').exists()).toBe(true)
  })

  it('renders csv placeholder icon for csv kind', () => {
    const wrapper = mountComponent({ mediaKind: 'csv' })
    expect(wrapper.find('.tp-card-placeholder--csv').exists()).toBe(true)
  })

  it('renders ppt placeholder icon for ppt kind', () => {
    const wrapper = mountComponent({ mediaKind: 'ppt' })
    expect(wrapper.find('.tp-card-placeholder--ppt').exists()).toBe(true)
  })

  it('renders pdf placeholder icon for pdf kind', () => {
    const wrapper = mountComponent({ mediaKind: 'pdf' })
    expect(wrapper.find('.tp-card-placeholder--pdf').exists()).toBe(true)
  })

  it('passes labelWidth and labelHeight to LabelPreview', () => {
    const wrapper = mountComponent({ mediaKind: '', template: { category: 'label' }, labelWidth: 400, labelHeight: 300 })
    const label = wrapper.findComponent({ name: 'LabelPreview' })
    expect(label.props('width')).toBe(400)
    expect(label.props('height')).toBe(300)
  })

  it('passes fields and sampleRows to ExcelPreview', () => {
    const wrapper = mountComponent({
      mediaKind: 'excel',
      showExcelGrid: true,
      fields: [{ label: 'a' }],
      sampleRows: [[1]],
      excelTitle: '我的标题',
      rows: 10,
      columns: 8,
    })
    const excel = wrapper.findComponent({ name: 'ExcelPreview' })
    expect(excel.props('fields')).toEqual([{ label: 'a' }])
    expect(excel.props('sampleRows')).toEqual([[1]])
    expect(excel.props('title')).toBe('我的标题')
    expect(excel.props('rows')).toBe(10)
    expect(excel.props('columns')).toBe(8)
  })

  it('rootClass applies compact class in DOM', () => {
    const wrapper = mountComponent({ compact: true })
    expect(wrapper.find('.template-media-preview--compact').exists()).toBe(true)
  })
})
