import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import FileUploadStep from './FileUploadStep.vue'

function createFile(name: string, size = 1024): File {
  const blob = new Blob(['dummy'], { type: 'application/octet-stream' })
  // jsdom File doesn't allow setting size directly; mock via defineProperty
  const file = new File([blob], name)
  Object.defineProperty(file, 'size', { value: size, configurable: true })
  return file
}

function mountFileUploadStep(props: Record<string, unknown> = {}) {
  return mount(FileUploadStep, {
    props: {
      templateName: '',
      selectedFile: null,
      ...props,
    },
  })
}

describe('FileUploadStep.vue functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('computed.uploadAccept', () => {
    it('returns the TEMPLATE_MEDIA_ACCEPT value', () => {
      const wrapper = mountFileUploadStep()
      expect(wrapper.vm.uploadAccept).toBe('.xlsx,.xls,.docx,.csv,.pptx,.pdf')
    })
  })

  describe('computed.uploadHint', () => {
    it('returns the upload hint string', () => {
      const wrapper = mountFileUploadStep()
      expect(wrapper.vm.uploadHint).toContain('Excel')
      expect(wrapper.vm.uploadHint).toContain('PDF')
    })
  })

  describe('computed.recognizedTypeLabel', () => {
    it('returns "未知" when recognizedType is null', () => {
      const wrapper = mountFileUploadStep()
      expect(wrapper.vm.recognizedTypeLabel).toBe('未知')
    })

    it('returns "Excel 模板" when recognizedType is excel', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.recognizedType = 'excel'
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.recognizedTypeLabel).toBe('Excel 模板')
    })

    it('returns "Word 模板" when recognizedType is word', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.recognizedType = 'word'
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.recognizedTypeLabel).toBe('Word 模板')
    })

    it('returns "CSV 模板" when recognizedType is csv', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.recognizedType = 'csv'
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.recognizedTypeLabel).toBe('CSV 模板')
    })

    it('returns "PPT 模板" when recognizedType is ppt', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.recognizedType = 'ppt'
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.recognizedTypeLabel).toBe('PPT 模板')
    })

    it('returns "PDF 模板" when recognizedType is pdf', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.recognizedType = 'pdf'
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.recognizedTypeLabel).toBe('PDF 模板')
    })

    it('returns "未知" when recognizedType is an invalid string', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.recognizedType = 'invalid'
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.recognizedTypeLabel).toBe('未知')
    })
  })

  describe('triggerFileInput', () => {
    it('calls click on the file input ref', async () => {
      const wrapper = mountFileUploadStep()
      const clickSpy = vi.fn()
      // Stub the file input element with a click spy before triggering
      const inputEl = wrapper.find('input[type="file"]').element
      vi.spyOn(inputEl, 'click').mockImplementation(clickSpy)
      wrapper.vm.triggerFileInput()
      expect(clickSpy).toHaveBeenCalledTimes(1)
    })
  })

  describe('handleFileSelect', () => {
    it('calls selectFile when a file is present in event', async () => {
      const wrapper = mountFileUploadStep()
      const selectSpy = vi.spyOn(wrapper.vm, 'selectFile')
      const file = createFile('test.xlsx')
      wrapper.vm.handleFileSelect({ target: { files: [file] } })
      expect(selectSpy).toHaveBeenCalledWith(file)
    })

    it('does not call selectFile when no file in event', async () => {
      const wrapper = mountFileUploadStep()
      const selectSpy = vi.spyOn(wrapper.vm, 'selectFile')
      wrapper.vm.handleFileSelect({ target: { files: [] } })
      expect(selectSpy).not.toHaveBeenCalled()
    })

    it('does not call selectFile when files[0] is undefined', async () => {
      const wrapper = mountFileUploadStep()
      const selectSpy = vi.spyOn(wrapper.vm, 'selectFile')
      wrapper.vm.handleFileSelect({ target: { files: [undefined] } })
      expect(selectSpy).not.toHaveBeenCalled()
    })
  })

  describe('handleDrop', () => {
    it('sets isDragover to false and calls selectFile with dropped file', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.isDragover = true
      const selectSpy = vi.spyOn(wrapper.vm, 'selectFile')
      const file = createFile('dropped.xlsx')
      wrapper.vm.handleDrop({ dataTransfer: { files: [file] } })
      expect(wrapper.vm.isDragover).toBe(false)
      expect(selectSpy).toHaveBeenCalledWith(file)
    })

    it('sets isDragover to false even when no file dropped', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.isDragover = true
      const selectSpy = vi.spyOn(wrapper.vm, 'selectFile')
      wrapper.vm.handleDrop({ dataTransfer: { files: [] } })
      expect(wrapper.vm.isDragover).toBe(false)
      expect(selectSpy).not.toHaveBeenCalled()
    })
  })

  describe('selectFile', () => {
    it('sets analyzeError when file kind is null (unknown extension)', async () => {
      const wrapper = mountFileUploadStep()
      const file = createFile('unknown.txt')
      wrapper.vm.selectFile(file)
      expect(wrapper.vm.analyzeError).toBeTruthy()
      expect(wrapper.vm.localSelectedFile).toBeNull()
    })

    it('sets analyzeError when file name has no extension', async () => {
      const wrapper = mountFileUploadStep()
      const file = createFile('noextension')
      wrapper.vm.selectFile(file)
      expect(wrapper.vm.analyzeError).toBeTruthy()
    })

    it('accepts an excel file and emits update:selected-file and file-selected', async () => {
      const wrapper = mountFileUploadStep()
      const file = createFile('data.xlsx')
      wrapper.vm.selectFile(file)
      expect(wrapper.vm.localSelectedFile).toBe(file)
      expect(wrapper.vm.recognizedType).toBe('excel')
      expect(wrapper.vm.analyzeError).toBeNull()
      expect(wrapper.emitted('update:selected-file')).toBeTruthy()
      expect(wrapper.emitted('update:selected-file')[0]).toEqual([file])
      expect(wrapper.emitted('file-selected')).toBeTruthy()
      const emitted = wrapper.emitted('file-selected')[0][0]
      expect(emitted.selectedFile).toBe(file)
      expect(emitted.recognizedType).toBe('excel')
    })

    it('accepts a word file and sets recognizedType to word', async () => {
      const wrapper = mountFileUploadStep()
      const file = createFile('doc.docx')
      wrapper.vm.selectFile(file)
      expect(wrapper.vm.recognizedType).toBe('word')
    })

    it('accepts a csv file and sets recognizedType to csv', async () => {
      const wrapper = mountFileUploadStep()
      const file = createFile('data.csv')
      wrapper.vm.selectFile(file)
      expect(wrapper.vm.recognizedType).toBe('csv')
    })

    it('accepts a ppt file and sets recognizedType to ppt', async () => {
      const wrapper = mountFileUploadStep()
      const file = createFile('slides.pptx')
      wrapper.vm.selectFile(file)
      expect(wrapper.vm.recognizedType).toBe('ppt')
    })

    it('accepts a pdf file and sets recognizedType to pdf', async () => {
      const wrapper = mountFileUploadStep()
      const file = createFile('doc.pdf')
      wrapper.vm.selectFile(file)
      expect(wrapper.vm.recognizedType).toBe('pdf')
    })

    it('accepts legacy .xls extension as excel', async () => {
      const wrapper = mountFileUploadStep()
      const file = createFile('legacy.xls')
      wrapper.vm.selectFile(file)
      expect(wrapper.vm.recognizedType).toBe('excel')
    })
  })

  describe('clearFile', () => {
    it('clears localSelectedFile and recognizedType', async () => {
      const wrapper = mountFileUploadStep()
      const file = createFile('data.xlsx')
      wrapper.vm.selectFile(file)
      // mock the fileInput ref
      wrapper.vm.$refs.fileInput = { value: 'dummy' }
      wrapper.vm.clearFile()
      expect(wrapper.vm.localSelectedFile).toBeNull()
      expect(wrapper.vm.recognizedType).toBeNull()
      expect(wrapper.vm.analyzeError).toBeNull()
      expect(wrapper.emitted('update:selected-file')).toBeTruthy()
      expect(wrapper.emitted('update:selected-file').slice(-1)[0]).toEqual([null])
    })
  })

  describe('onTemplateNameChange', () => {
    it('emits update:template-name and file-selected', async () => {
      const wrapper = mountFileUploadStep({ templateName: 'old' })
      wrapper.vm.localTemplateName = 'new name'
      wrapper.vm.onTemplateNameChange()
      expect(wrapper.emitted('update:template-name')).toBeTruthy()
      expect(wrapper.emitted('update:template-name')[0]).toEqual(['new name'])
      expect(wrapper.emitted('file-selected')).toBeTruthy()
    })
  })

  describe('getFileIconClass', () => {
    it('returns fa-folder-open-o when no file selected', () => {
      const wrapper = mountFileUploadStep()
      expect(wrapper.vm.getFileIconClass()).toBe('fa-folder-open-o')
    })

    it('returns fa-file-excel-o for xlsx files', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.selectFile(createFile('data.xlsx'))
      expect(wrapper.vm.getFileIconClass()).toBe('fa-file-excel-o')
    })

    it('returns fa-file-word-o for docx files', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.selectFile(createFile('doc.docx'))
      expect(wrapper.vm.getFileIconClass()).toBe('fa-file-word-o')
    })

    it('returns fa-file-text-o for csv files', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.selectFile(createFile('data.csv'))
      expect(wrapper.vm.getFileIconClass()).toBe('fa-file-text-o')
    })

    it('returns fa-file-powerpoint-o for pptx files', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.selectFile(createFile('slides.pptx'))
      expect(wrapper.vm.getFileIconClass()).toBe('fa-file-powerpoint-o')
    })

    it('returns fa-file-pdf-o for pdf files', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.selectFile(createFile('doc.pdf'))
      expect(wrapper.vm.getFileIconClass()).toBe('fa-file-pdf-o')
    })

    it('returns fa-file-o for unknown extensions', async () => {
      const wrapper = mountFileUploadStep()
      // manually set localSelectedFile since selectFile rejects unknown types
      wrapper.vm.localSelectedFile = createFile('unknown.xyz')
      expect(wrapper.vm.getFileIconClass()).toBe('fa-file-o')
    })
  })

  describe('formatFileSize', () => {
    it('formats bytes (< 1024) with B suffix', () => {
      const wrapper = mountFileUploadStep()
      expect(wrapper.vm.formatFileSize(0)).toBe('0 B')
      expect(wrapper.vm.formatFileSize(512)).toBe('512 B')
      expect(wrapper.vm.formatFileSize(1023)).toBe('1023 B')
    })

    it('formats kilobytes (1024 <= bytes < 1MB) with KB suffix', () => {
      const wrapper = mountFileUploadStep()
      expect(wrapper.vm.formatFileSize(1024)).toBe('1.0 KB')
      expect(wrapper.vm.formatFileSize(2048)).toBe('2.0 KB')
      expect(wrapper.vm.formatFileSize(1536)).toBe('1.5 KB')
    })

    it('formats megabytes (>= 1MB) with MB suffix', () => {
      const wrapper = mountFileUploadStep()
      expect(wrapper.vm.formatFileSize(1024 * 1024)).toBe('1.0 MB')
      expect(wrapper.vm.formatFileSize(2 * 1024 * 1024)).toBe('2.0 MB')
      expect(wrapper.vm.formatFileSize(1.5 * 1024 * 1024)).toBe('1.5 MB')
    })

    it('formats 10 MB correctly', () => {
      const wrapper = mountFileUploadStep()
      expect(wrapper.vm.formatFileSize(10 * 1024 * 1024)).toBe('10.0 MB')
    })
  })

  describe('getData', () => {
    it('returns object with current state', async () => {
      const wrapper = mountFileUploadStep({ templateName: 'My Template' })
      const file = createFile('data.xlsx')
      wrapper.vm.selectFile(file)
      const data = wrapper.vm.getData()
      expect(data.templateName).toBe('My Template')
      expect(data.selectedFile).toBe(file)
      expect(data.recognizedType).toBe('excel')
    })

    it('returns null selectedFile and recognizedType when nothing selected', () => {
      const wrapper = mountFileUploadStep()
      const data = wrapper.vm.getData()
      expect(data.selectedFile).toBeNull()
      expect(data.recognizedType).toBeNull()
    })
  })

  describe('validate', () => {
    it('returns false and sets analyzeError when templateName is empty', () => {
      const wrapper = mountFileUploadStep({ templateName: '' })
      const result = wrapper.vm.validate()
      expect(result).toBe(false)
      expect(wrapper.vm.analyzeError).toBe('请输入模板名称')
    })

    it('returns false and sets analyzeError when templateName is whitespace only', () => {
      const wrapper = mountFileUploadStep({ templateName: '   ' })
      const result = wrapper.vm.validate()
      expect(result).toBe(false)
      expect(wrapper.vm.analyzeError).toBe('请输入模板名称')
    })

    it('returns false and sets analyzeError when no file selected', async () => {
      const wrapper = mountFileUploadStep({ templateName: 'My Template' })
      const result = wrapper.vm.validate()
      expect(result).toBe(false)
      expect(wrapper.vm.analyzeError).toBe('请上传文件')
    })

    it('returns true when both templateName and file are provided', async () => {
      const wrapper = mountFileUploadStep({ templateName: 'My Template' })
      wrapper.vm.selectFile(createFile('data.xlsx'))
      wrapper.vm.analyzeError = null
      const result = wrapper.vm.validate()
      expect(result).toBe(true)
      expect(wrapper.vm.analyzeError).toBeNull()
    })
  })

  describe('watchers', () => {
    it('updates localTemplateName when templateName prop changes', async () => {
      const wrapper = mountFileUploadStep({ templateName: 'old' })
      expect(wrapper.vm.localTemplateName).toBe('old')
      await wrapper.setProps({ templateName: 'new' })
      expect(wrapper.vm.localTemplateName).toBe('new')
    })

    it('updates localSelectedFile when selectedFile prop changes', async () => {
      const wrapper = mountFileUploadStep({ selectedFile: null })
      const file = createFile('data.xlsx')
      await wrapper.setProps({ selectedFile: file })
      expect(wrapper.vm.localSelectedFile).toBe(file)
    })
  })

  describe('UI interactions', () => {
    it('renders upload placeholder when no file selected', () => {
      const wrapper = mountFileUploadStep()
      expect(wrapper.find('.upload-placeholder').exists()).toBe(true)
    })

    it('renders file info when file is selected', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.selectFile(createFile('data.xlsx'))
      await wrapper.vm.$nextTick()
      expect(wrapper.find('.file-info').exists()).toBe(true)
      expect(wrapper.find('.upload-placeholder').exists()).toBe(false)
    })

    it('shows recognized type badge when recognizedType is set', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.recognizedType = 'excel'
      await wrapper.vm.$nextTick()
      expect(wrapper.find('.recognized-type').exists()).toBe(true)
    })

    it('shows analyze error alert when analyzeError is set', async () => {
      const wrapper = mountFileUploadStep()
      wrapper.vm.analyzeError = 'Some error'
      await wrapper.vm.$nextTick()
      expect(wrapper.find('.alert-danger').exists()).toBe(true)
      expect(wrapper.text()).toContain('Some error')
    })
  })
})
