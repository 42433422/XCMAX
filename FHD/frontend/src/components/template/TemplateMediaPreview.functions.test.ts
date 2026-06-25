import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import TemplateMediaPreview from './TemplateMediaPreview.vue'

vi.mock('@/components/template/ExcelPreview.vue', () => ({
  default: {
    name: 'ExcelPreview',
    template: '<div class="excel-preview-stub" />',
  },
}))

vi.mock('@/components/template/LabelPreview.vue', () => ({
  default: {
    name: 'LabelPreview',
    template: '<div class="label-preview-stub" />',
  },
}))

function mountPreview(props: Record<string, unknown> = {}) {
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
      ...props,
    },
  })
}

describe('TemplateMediaPreview.vue functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('computed.resolvedMediaKind', () => {
    it('returns mediaKind prop when it is a valid kind', () => {
      const wrapper = mountPreview({ mediaKind: 'excel' })
      expect(wrapper.vm.resolvedMediaKind).toBe('excel')
    })

    it('returns word when mediaKind is word', () => {
      const wrapper = mountPreview({ mediaKind: 'word' })
      expect(wrapper.vm.resolvedMediaKind).toBe('word')
    })

    it('returns csv when mediaKind is csv', () => {
      const wrapper = mountPreview({ mediaKind: 'csv' })
      expect(wrapper.vm.resolvedMediaKind).toBe('csv')
    })

    it('returns ppt when mediaKind is ppt', () => {
      const wrapper = mountPreview({ mediaKind: 'ppt' })
      expect(wrapper.vm.resolvedMediaKind).toBe('ppt')
    })

    it('returns pdf when mediaKind is pdf', () => {
      const wrapper = mountPreview({ mediaKind: 'pdf' })
      expect(wrapper.vm.resolvedMediaKind).toBe('pdf')
    })

    it('returns label when template.category is label', () => {
      const wrapper = mountPreview({
        mediaKind: '',
        template: { category: 'label' },
      })
      expect(wrapper.vm.resolvedMediaKind).toBe('label')
    })

    it('returns excel (default fallback) when mediaKind empty and template.category is excel', () => {
      const wrapper = mountPreview({
        mediaKind: '',
        template: { category: 'excel' },
      })
      expect(wrapper.vm.resolvedMediaKind).toBe('excel')
    })

    it('returns excel (default fallback) when mediaKind empty and template.category is invalid', () => {
      const wrapper = mountPreview({
        mediaKind: '',
        template: { category: 'invalid' },
      })
      expect(wrapper.vm.resolvedMediaKind).toBe('excel')
    })

    it('returns excel (default fallback) when mediaKind and template are both empty', () => {
      const wrapper = mountPreview({ mediaKind: '', template: null })
      expect(wrapper.vm.resolvedMediaKind).toBe('excel')
    })

    it('returns excel when mediaKind is invalid string', () => {
      const wrapper = mountPreview({ mediaKind: 'invalid' })
      expect(wrapper.vm.resolvedMediaKind).toBe('excel')
    })

    it('trims whitespace from mediaKind', () => {
      const wrapper = mountPreview({ mediaKind: '  excel  ' })
      expect(wrapper.vm.resolvedMediaKind).toBe('excel')
    })

    it('trims whitespace from template.category', () => {
      const wrapper = mountPreview({
        mediaKind: '',
        template: { category: '  label  ' },
      })
      expect(wrapper.vm.resolvedMediaKind).toBe('label')
    })

    it('prefers mediaKind over template.category', () => {
      const wrapper = mountPreview({
        mediaKind: 'word',
        template: { category: 'excel' },
      })
      expect(wrapper.vm.resolvedMediaKind).toBe('word')
    })
  })

  describe('computed.iconClass', () => {
    it('returns excel icon for excel kind', () => {
      const wrapper = mountPreview({ mediaKind: 'excel' })
      expect(wrapper.vm.iconClass).toBe('fa-file-excel-o')
    })

    it('returns word icon for word kind', () => {
      const wrapper = mountPreview({ mediaKind: 'word' })
      expect(wrapper.vm.iconClass).toBe('fa-file-word-o')
    })

    it('returns csv icon for csv kind', () => {
      const wrapper = mountPreview({ mediaKind: 'csv' })
      expect(wrapper.vm.iconClass).toBe('fa-file-text-o')
    })

    it('returns ppt icon for ppt kind', () => {
      const wrapper = mountPreview({ mediaKind: 'ppt' })
      expect(wrapper.vm.iconClass).toBe('fa-file-powerpoint-o')
    })

    it('returns pdf icon for pdf kind', () => {
      const wrapper = mountPreview({ mediaKind: 'pdf' })
      expect(wrapper.vm.iconClass).toBe('fa-file-pdf-o')
    })

    it('returns default icon for label kind (not in icon map)', () => {
      const wrapper = mountPreview({ mediaKind: '', template: { category: 'label' } })
      expect(wrapper.vm.iconClass).toBe('fa-file-o')
    })
  })

  describe('computed.uploadHint', () => {
    it('returns the upload hint string', () => {
      const wrapper = mountPreview()
      expect(wrapper.vm.uploadHint).toContain('Excel')
      expect(wrapper.vm.uploadHint).toContain('PDF')
    })
  })

  describe('computed.isVirtualPlaceholder', () => {
    it('returns true when virtual=true, showExcelGrid=false, and kind is not label', () => {
      const wrapper = mountPreview({ virtual: true, showExcelGrid: false, mediaKind: 'excel' })
      expect(wrapper.vm.isVirtualPlaceholder).toBe(true)
    })

    it('returns false when virtual=false', () => {
      const wrapper = mountPreview({ virtual: false, mediaKind: 'excel' })
      expect(wrapper.vm.isVirtualPlaceholder).toBe(false)
    })

    it('returns false when showExcelGrid=true', () => {
      const wrapper = mountPreview({ virtual: true, showExcelGrid: true, mediaKind: 'excel' })
      expect(wrapper.vm.isVirtualPlaceholder).toBe(false)
    })

    it('returns false when kind is label', () => {
      const wrapper = mountPreview({
        virtual: true,
        showExcelGrid: false,
        mediaKind: '',
        template: { category: 'label' },
      })
      expect(wrapper.vm.isVirtualPlaceholder).toBe(false)
    })

    it('returns true when virtual=true and mediaKind is empty (defaults to excel)', () => {
      const wrapper = mountPreview({ virtual: true, showExcelGrid: false, mediaKind: '' })
      expect(wrapper.vm.isVirtualPlaceholder).toBe(true)
    })
  })

  describe('computed.rootClass', () => {
    it('includes compact class when compact=true', () => {
      const wrapper = mountPreview({ compact: true, mediaKind: 'excel' })
      expect(wrapper.vm.rootClass['template-media-preview--compact']).toBe(true)
    })

    it('does not include compact class when compact=false', () => {
      const wrapper = mountPreview({ compact: false, mediaKind: 'excel' })
      expect(wrapper.vm.rootClass['template-media-preview--compact']).toBe(false)
    })

    it('includes kind class for excel', () => {
      const wrapper = mountPreview({ mediaKind: 'excel' })
      expect(wrapper.vm.rootClass['template-media-preview--excel']).toBe(true)
    })

    it('includes kind class for word', () => {
      const wrapper = mountPreview({ mediaKind: 'word' })
      expect(wrapper.vm.rootClass['template-media-preview--word']).toBe(true)
    })

    it('includes kind class for label', () => {
      const wrapper = mountPreview({ mediaKind: '', template: { category: 'label' } })
      expect(wrapper.vm.rootClass['template-media-preview--label']).toBe(true)
    })

    it('includes kind class for default excel', () => {
      const wrapper = mountPreview({ mediaKind: '' })
      expect(wrapper.vm.rootClass['template-media-preview--excel']).toBe(true)
    })
  })

  describe('rendering', () => {
    it('renders ExcelPreview when kind is excel and showExcelGrid is true', () => {
      const wrapper = mountPreview({ mediaKind: 'excel', showExcelGrid: true })
      expect(wrapper.findComponent({ name: 'ExcelPreview' }).exists()).toBe(true)
    })

    it('does not render ExcelPreview when showExcelGrid is false', () => {
      const wrapper = mountPreview({ mediaKind: 'excel', showExcelGrid: false })
      expect(wrapper.findComponent({ name: 'ExcelPreview' }).exists()).toBe(false)
    })

    it('renders virtual placeholder when virtual=true and not excel grid', () => {
      const wrapper = mountPreview({ virtual: true, showExcelGrid: false, mediaKind: 'excel' })
      expect(wrapper.find('.tp-card-placeholder').exists()).toBe(true)
      expect(wrapper.find('.tp-placeholder-title').exists()).toBe(true)
    })

    it('renders required terms in virtual placeholder when provided', () => {
      const wrapper = mountPreview({
        virtual: true,
        showExcelGrid: false,
        mediaKind: 'excel',
        requiredTerms: ['品名', '规格'],
      })
      expect(wrapper.find('.tp-placeholder-terms').exists()).toBe(true)
      expect(wrapper.text()).toContain('品名')
      expect(wrapper.text()).toContain('规格')
    })

    it('renders upload hint in virtual placeholder when no required terms', () => {
      const wrapper = mountPreview({
        virtual: true,
        showExcelGrid: false,
        mediaKind: 'excel',
        requiredTerms: [],
      })
      expect(wrapper.find('.tp-placeholder-terms').exists()).toBe(true)
      expect(wrapper.text()).toContain('Excel')
    })

    it('renders LabelPreview when kind is label', () => {
      const wrapper = mountPreview({
        mediaKind: '',
        template: { category: 'label' },
        fields: [{ label: '品名', value: '鞋', type: 'fixed' }],
      })
      expect(wrapper.findComponent({ name: 'LabelPreview' }).exists()).toBe(true)
    })

    it('renders default placeholder with icon for word kind', () => {
      const wrapper = mountPreview({ mediaKind: 'word', displayName: 'doc.docx' })
      expect(wrapper.find('.tp-card-placeholder--word').exists()).toBe(true)
      expect(wrapper.text()).toContain('doc.docx')
    })

    it('renders status hint when provided', () => {
      const wrapper = mountPreview({
        mediaKind: 'word',
        displayName: 'doc.docx',
        statusHint: 'Processing...',
      })
      expect(wrapper.find('.tmp-status').exists()).toBe(true)
      expect(wrapper.text()).toContain('Processing...')
    })

    it('does not render status hint when empty', () => {
      const wrapper = mountPreview({ mediaKind: 'word', statusHint: '' })
      expect(wrapper.find('.tmp-status').exists()).toBe(false)
    })
  })
})
