import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

import FileUploadStep from '@/components/template/FileUploadStep.vue'

function makeFile(name = 'test.xlsx', size = 1024) {
  return new File([new Array(size).fill('a').join('')], name, {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

function mountComponent(propsOverrides = {}) {
  return mount(FileUploadStep, {
    props: {
      templateName: '出货单模板',
      selectedFile: null,
      ...propsOverrides,
    },
  })
}

describe('FileUploadStep.coverage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders template name input with provided value', () => {
    const wrapper = mountComponent()
    const input = wrapper.find('input[type="text"]')
    expect((input.element as HTMLInputElement).value).toBe('出货单模板')
  })

  it('renders upload area placeholder when no file', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.upload-placeholder').exists()).toBe(true)
  })

  it('renders upload hint text', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('Excel')
  })

  it('uploadAccept computed returns accept string', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).uploadAccept).toContain('.xlsx')
  })

  it('uploadHint computed returns hint string', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).uploadHint).toContain('Excel')
  })

  it('recognizedTypeLabel returns 未知 when recognizedType is null', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).recognizedTypeLabel).toBe('未知')
  })

  it('recognizedTypeLabel returns label when recognizedType is set', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).recognizedType = 'excel'
    await nextTick()
    expect((wrapper.vm as any).recognizedTypeLabel).toBe('Excel 模板')
  })

  it('recognizedTypeLabel returns 未知 for invalid type', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).recognizedType = 'invalid'
    await nextTick()
    expect((wrapper.vm as any).recognizedTypeLabel).toBe('未知')
  })

  it('watch templateName updates localTemplateName', async () => {
    const wrapper = mountComponent()
    await wrapper.setProps({ templateName: '新模板名' })
    expect((wrapper.vm as any).localTemplateName).toBe('新模板名')
  })

  it('watch selectedFile updates localSelectedFile', async () => {
    const wrapper = mountComponent()
    const file = makeFile()
    await wrapper.setProps({ selectedFile: file })
    expect((wrapper.vm as any).localSelectedFile).toBe(file)
  })

  it('triggerFileInput calls click on file input ref', async () => {
    const wrapper = mountComponent()
    const fileInput = wrapper.find('input[type="file"]').element as HTMLInputElement
    const clickSpy = vi.spyOn(fileInput, 'click').mockImplementation(() => {})
    ;(wrapper.vm as any).triggerFileInput()
    expect(clickSpy).toHaveBeenCalled()
    clickSpy.mockRestore()
  })

  it('triggerFileInput via upload area click calls file input click', async () => {
    const wrapper = mountComponent()
    const fileInput = wrapper.find('input[type="file"]').element as HTMLInputElement
    const clickSpy = vi.spyOn(fileInput, 'click').mockImplementation(() => {})
    await wrapper.find('.upload-area').trigger('click')
    expect(clickSpy).toHaveBeenCalled()
    clickSpy.mockRestore()
  })

  it('handleFileSelect selects file when present', async () => {
    const wrapper = mountComponent()
    const file = makeFile('report.xlsx')
    const event = { target: { files: [file] } }
    await (wrapper.vm as any).handleFileSelect(event)
    expect((wrapper.vm as any).localSelectedFile).toBe(file)
    expect(wrapper.emitted('file-selected')).toBeTruthy()
  })

  it('handleFileSelect does nothing when no file', async () => {
    const wrapper = mountComponent()
    const event = { target: { files: [] } }
    await (wrapper.vm as any).handleFileSelect(event)
    expect((wrapper.vm as any).localSelectedFile).toBeNull()
    expect(wrapper.emitted('file-selected')).toBeFalsy()
  })

  it('handleFileSelect via input change selects file', async () => {
    const wrapper = mountComponent()
    const file = makeFile('data.csv')
    Object.defineProperty(wrapper.find('input[type="file"]').element, 'files', {
      value: [file],
      configurable: true,
    })
    await wrapper.find('input[type="file"]').trigger('change')
    expect((wrapper.vm as any).localSelectedFile).toBe(file)
  })

  it('handleDrop selects file from dataTransfer', async () => {
    const wrapper = mountComponent()
    const file = makeFile('dropped.docx')
    const event = { dataTransfer: { files: [file] } }
    await (wrapper.vm as any).handleDrop(event)
    expect((wrapper.vm as any).isDragover).toBe(false)
    expect((wrapper.vm as any).localSelectedFile).toBe(file)
    expect((wrapper.vm as any).recognizedType).toBe('word')
  })

  it('handleDrop does nothing when no file', async () => {
    const wrapper = mountComponent()
    const event = { dataTransfer: { files: [] } }
    await (wrapper.vm as any).handleDrop(event)
    expect((wrapper.vm as any).localSelectedFile).toBeNull()
  })

  it('dragover sets isDragover true', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.upload-area').trigger('dragover.prevent')
    expect((wrapper.vm as any).isDragover).toBe(true)
  })

  it('dragleave sets isDragover false', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).isDragover = true
    await wrapper.find('.upload-area').trigger('dragleave.prevent')
    expect((wrapper.vm as any).isDragover).toBe(false)
  })

  it('selectFile with valid excel file emits update and file-selected', async () => {
    const wrapper = mountComponent()
    const file = makeFile('sheet.xlsx')
    await (wrapper.vm as any).selectFile(file)
    expect((wrapper.vm as any).localSelectedFile).toBe(file)
    expect((wrapper.vm as any).recognizedType).toBe('excel')
    expect(wrapper.emitted('update:selected-file')).toBeTruthy()
    expect(wrapper.emitted('file-selected')).toBeTruthy()
    const evt = wrapper.emitted('file-selected')![0][0]
    expect(evt.recognizedType).toBe('excel')
  })

  it('selectFile with unsupported extension sets analyzeError and returns', async () => {
    const wrapper = mountComponent()
    const file = makeFile('unknown.txt')
    await (wrapper.vm as any).selectFile(file)
    expect((wrapper.vm as any).localSelectedFile).toBeNull()
    expect((wrapper.vm as any).analyzeError).toBeTruthy()
    expect(wrapper.emitted('file-selected')).toBeFalsy()
  })

  it('selectFile with null file sets analyzeError', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(null)
    expect((wrapper.vm as any).analyzeError).toBeTruthy()
    expect((wrapper.vm as any).localSelectedFile).toBeNull()
  })

  it('selectFile with word file recognizes word type', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('doc.docx'))
    expect((wrapper.vm as any).recognizedType).toBe('word')
  })

  it('selectFile with csv file recognizes csv type', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('data.csv'))
    expect((wrapper.vm as any).recognizedType).toBe('csv')
  })

  it('selectFile with ppt file recognizes ppt type', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('slides.pptx'))
    expect((wrapper.vm as any).recognizedType).toBe('ppt')
  })

  it('selectFile with pdf file recognizes pdf type', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('doc.pdf'))
    expect((wrapper.vm as any).recognizedType).toBe('pdf')
  })

  it('clearFile resets state and emits update', async () => {
    const wrapper = mountComponent()
    const file = makeFile('sheet.xlsx')
    await (wrapper.vm as any).selectFile(file)
    ;(wrapper.vm as any).$refs.fileInput = { value: 'x' }
    await (wrapper.vm as any).clearFile()
    expect((wrapper.vm as any).localSelectedFile).toBeNull()
    expect((wrapper.vm as any).recognizedType).toBeNull()
    expect((wrapper.vm as any).analyzeError).toBeNull()
    expect(wrapper.emitted('update:selected-file')).toBeTruthy()
    const lastUpdate = wrapper.emitted('update:selected-file')!.slice(-1)[0]
    expect(lastUpdate[0]).toBeNull()
  })

  it('clearFile via delete button click resets state', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('sheet.xlsx'))
    await nextTick()
    const btn = wrapper.find('.btn-danger')
    await btn.trigger('click')
    expect((wrapper.vm as any).localSelectedFile).toBeNull()
  })

  it('onTemplateNameChange emits update:template-name and file-selected', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).localTemplateName = '新名称'
    await (wrapper.vm as any).onTemplateNameChange()
    expect(wrapper.emitted('update:template-name')).toBeTruthy()
    expect(wrapper.emitted('update:template-name')![0][0]).toBe('新名称')
    expect(wrapper.emitted('file-selected')).toBeTruthy()
  })

  it('onTemplateNameChange via input event emits update', async () => {
    const wrapper = mountComponent()
    const input = wrapper.find('input[type="text"]')
    await input.setValue('改名后')
    await input.trigger('input')
    expect(wrapper.emitted('update:template-name')).toBeTruthy()
  })

  it('getFileIconClass returns folder icon when no file', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).getFileIconClass()).toBe('fa-folder-open-o')
  })

  it('getFileIconClass returns excel icon for xlsx', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('a.xlsx'))
    expect((wrapper.vm as any).getFileIconClass()).toBe('fa-file-excel-o')
  })

  it('getFileIconClass returns word icon for docx', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('a.docx'))
    expect((wrapper.vm as any).getFileIconClass()).toBe('fa-file-word-o')
  })

  it('getFileIconClass returns csv icon for csv', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('a.csv'))
    expect((wrapper.vm as any).getFileIconClass()).toBe('fa-file-text-o')
  })

  it('getFileIconClass returns ppt icon for pptx', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('a.pptx'))
    expect((wrapper.vm as any).getFileIconClass()).toBe('fa-file-powerpoint-o')
  })

  it('getFileIconClass returns pdf icon for pdf', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('a.pdf'))
    expect((wrapper.vm as any).getFileIconClass()).toBe('fa-file-pdf-o')
  })

  it('getFileIconClass returns default icon for unsupported', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).localSelectedFile = { name: 'a.unknown' }
    expect((wrapper.vm as any).getFileIconClass()).toBe('fa-file-o')
  })

  it('formatFileSize returns B for bytes < 1024', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).formatFileSize(0)).toBe('0 B')
    expect((wrapper.vm as any).formatFileSize(512)).toBe('512 B')
  })

  it('formatFileSize returns KB for bytes < 1MB', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).formatFileSize(2048)).toBe('2.0 KB')
  })

  it('formatFileSize returns MB for bytes >= 1MB', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).formatFileSize(2 * 1024 * 1024)).toBe('2.0 MB')
  })

  it('getData returns current state object', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).localTemplateName = '模板A'
    await (wrapper.vm as any).selectFile(makeFile('a.xlsx'))
    const data = (wrapper.vm as any).getData()
    expect(data.templateName).toBe('模板A')
    expect(data.selectedFile).toBeTruthy()
    expect(data.recognizedType).toBe('excel')
  })

  it('validate returns false when templateName empty', () => {
    const wrapper = mountComponent({ templateName: '' })
    ;(wrapper.vm as any).localTemplateName = '   '
    const result = (wrapper.vm as any).validate()
    expect(result).toBe(false)
    expect((wrapper.vm as any).analyzeError).toBe('请输入模板名称')
  })

  it('validate returns false when no file selected', () => {
    const wrapper = mountComponent()
    const result = (wrapper.vm as any).validate()
    expect(result).toBe(false)
    expect((wrapper.vm as any).analyzeError).toBe('请上传文件')
  })

  it('validate returns true when name and file present', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('a.xlsx'))
    const result = (wrapper.vm as any).validate()
    expect(result).toBe(true)
  })

  it('renders file info when file selected', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('report.xlsx', 2048))
    expect(wrapper.find('.file-info').exists()).toBe(true)
    expect(wrapper.text()).toContain('report.xlsx')
    expect(wrapper.text()).toContain('2.0 KB')
  })

  it('renders recognized type badge when recognizedType set', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('report.xlsx'))
    expect(wrapper.find('.recognized-type').exists()).toBe(true)
    expect(wrapper.text()).toContain('Excel 模板')
  })

  it('renders analyze error alert when analyzeError set', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).analyzeError = '出错了'
    await nextTick()
    expect(wrapper.find('.alert-danger').exists()).toBe(true)
    expect(wrapper.text()).toContain('出错了')
  })

  it('upload area has has-file class when file selected', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).selectFile(makeFile('a.xlsx'))
    expect(wrapper.find('.upload-area').classes()).toContain('has-file')
  })

  it('upload area has dragover class when isDragover true', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).isDragover = true
    await nextTick()
    expect(wrapper.find('.upload-area').classes()).toContain('dragover')
  })
})
