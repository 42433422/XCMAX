import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref, reactive } from 'vue'

const uploadingRef = ref(false)
const progressRef = ref(0)
const progressTextRef = ref('准备上传...')
const statusReactive = reactive({ show: false, type: '', message: '' })
const detectFileTypeMock = vi.fn((file: File) => {
  if (file.name.endsWith('.xlsx')) return 'excel'
  if (file.name.endsWith('.csv')) return 'csv'
  if (file.name.endsWith('.jpg') || file.name.endsWith('.png')) return 'image'
  if (file.name.endsWith('.pdf')) return 'pdf'
  if (file.name.endsWith('.docx')) return 'word'
  return 'other'
})
const resetStateMock = vi.fn(() => {
  uploadingRef.value = false
  progressRef.value = 0
  progressTextRef.value = '准备上传...'
  statusReactive.show = false
  statusReactive.type = ''
  statusReactive.message = ''
})
const uploadFileMock = vi.fn()
const uploadMultipleFilesMock = vi.fn()

vi.mock('@/composables/useFileImport', () => ({
  default: () => ({
    uploading: uploadingRef,
    progress: progressRef,
    progressText: progressTextRef,
    status: statusReactive,
    detectFileType: detectFileTypeMock,
    resetState: resetStateMock,
    uploadFile: uploadFileMock,
    uploadMultipleFiles: uploadMultipleFilesMock,
  }),
  FILE_EXTENSIONS: {
    EXCEL: ['.xlsx', '.xls'],
    CSV: ['.csv'],
    IMAGE: ['.jpg', '.jpeg', '.png', '.gif', '.webp'],
    PDF: ['.pdf'],
    WORD: ['.doc', '.docx'],
  },
}))

import FileImport from './FileImport.vue'

function mountFileImport(props: Record<string, unknown> = {}) {
  return mount(FileImport, {
    props: {
      modelValue: true,
      ...props,
    },
    attachTo: document.body,
  })
}

function createFile(name: string, type = '', size = 1024): File {
  const file = new File([new Array(Math.max(1, size)).join('x')], name, { type })
  Object.defineProperty(file, 'size', { value: size, configurable: true, enumerable: true })
  Object.defineProperty(file, 'name', { value: name, configurable: true, enumerable: true })
  return file
}

describe('FileImport', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    uploadingRef.value = false
    progressRef.value = 0
    progressTextRef.value = '准备上传...'
    statusReactive.show = false
    statusReactive.type = ''
    statusReactive.message = ''
    uploadFileMock.mockResolvedValue({ success: true })
    uploadMultipleFilesMock.mockResolvedValue([{ file: 'a', type: 'excel', success: true, data: {} }])
  })

  it('renders overlay when modelValue is true', () => {
    const wrapper = mountFileImport({ modelValue: true })
    expect(wrapper.find('.file-import-overlay').exists()).toBe(true)
  })

  it('does not render overlay when modelValue is false', () => {
    const wrapper = mountFileImport({ modelValue: false })
    expect(wrapper.find('.file-import-overlay').exists()).toBe(false)
  })

  it('renders default title', () => {
    const wrapper = mountFileImport()
    expect(wrapper.find('.file-import-header h4').text()).toBe('文件导入')
  })

  it('renders custom title when provided', () => {
    const wrapper = mountFileImport({ title: '自定义标题' })
    expect(wrapper.find('.file-import-header h4').text()).toBe('自定义标题')
  })

  it('renders drop zone with hint text', () => {
    const wrapper = mountFileImport()
    expect(wrapper.find('.drop-zone').exists()).toBe(true)
    expect(wrapper.find('.drop-zone-title').text()).toContain('点击或拖拽文件')
  })

  it('renders default hint text', () => {
    const wrapper = mountFileImport()
    expect(wrapper.find('.drop-zone-hint').text()).toContain('Excel')
  })

  it('renders custom hint text when provided', () => {
    const wrapper = mountFileImport({ hint: '自定义提示' })
    expect(wrapper.find('.drop-zone-hint').text()).toBe('自定义提示')
  })

  it('renders supported formats text', () => {
    const wrapper = mountFileImport()
    expect(wrapper.find('.drop-zone-supported').text()).toContain('Excel')
    expect(wrapper.find('.drop-zone-supported').text()).toContain('PDF')
  })

  it('renders file input with accept attribute', () => {
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    expect(input.exists()).toBe(true)
    expect(input.attributes('accept')).toContain('.xlsx')
  })

  it('renders cancel and upload buttons in footer', () => {
    const wrapper = mountFileImport()
    const buttons = wrapper.findAll('.file-import-footer button')
    expect(buttons.length).toBe(2)
    expect(buttons[0].text()).toBe('取消')
    expect(buttons[1].text()).toContain('开始导入')
  })

  it('disables upload button when no files selected', () => {
    const wrapper = mountFileImport()
    const uploadBtn = wrapper.findAll('.file-import-footer button')[1]
    expect(uploadBtn.attributes('disabled')).toBeDefined()
  })

  it('emits update:modelValue=false when close button is clicked', async () => {
    const wrapper = mountFileImport()
    await wrapper.find('.close-btn').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')![0][0]).toBe(false)
  })

  it('emits update:modelValue=false when cancel button is clicked', async () => {
    const wrapper = mountFileImport()
    const cancelBtn = wrapper.findAll('.file-import-footer button')[0]
    await cancelBtn.trigger('click')
    expect(wrapper.emitted('update:modelValue')![0][0]).toBe(false)
  })

  it('emits update:modelValue=false when overlay background is clicked', async () => {
    const wrapper = mountFileImport()
    await wrapper.find('.file-import-overlay').trigger('click')
    expect(wrapper.emitted('update:modelValue')![0][0]).toBe(false)
  })

  it('does not close when uploading', async () => {
    uploadingRef.value = true
    const wrapper = mountFileImport()
    await wrapper.find('.close-btn').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeFalsy()
  })

  it('handles file selection via input change', async () => {
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file = createFile('test.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.find('.file-list').exists()).toBe(true)
    expect(wrapper.text()).toContain('test.xlsx')
  })

  it('renders file list with file name and size', async () => {
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file = createFile('test.xlsx', '', 2048)
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.find('.file-name').text()).toBe('test.xlsx')
    expect(wrapper.find('.file-size').text()).toContain('KB')
  })

  it('renders file type tag', async () => {
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file = createFile('test.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.find('.file-type-tag').text()).toBe('excel')
  })

  it('clears files when clear button is clicked', async () => {
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file = createFile('test.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.find('.file-list').exists()).toBe(true)
    await wrapper.find('.clear-btn').trigger('click')
    expect(wrapper.find('.file-list').exists()).toBe(false)
    expect(resetStateMock).toHaveBeenCalled()
  })

  it('uploads single file when upload button is clicked', async () => {
    uploadFileMock.mockResolvedValue({ success: true, data: {} })
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file = createFile('test.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    const uploadBtn = wrapper.findAll('.file-import-footer button')[1]
    await uploadBtn.trigger('click')
    await flushPromises()
    expect(uploadFileMock).toHaveBeenCalled()
    expect(wrapper.emitted('uploaded')).toBeTruthy()
  })

  it('emits error when upload returns null', async () => {
    uploadFileMock.mockResolvedValue(null)
    statusReactive.message = '上传失败'
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file = createFile('test.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    const uploadBtn = wrapper.findAll('.file-import-footer button')[1]
    await uploadBtn.trigger('click')
    await flushPromises()
    expect(wrapper.emitted('error')).toBeTruthy()
  })

  it('emits progress during upload', async () => {
    uploadFileMock.mockImplementation(async (_file, _purpose, onProgress) => {
      onProgress?.(50, 'test.xlsx')
      return { success: true }
    })
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file = createFile('test.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    const uploadBtn = wrapper.findAll('.file-import-footer button')[1]
    await uploadBtn.trigger('click')
    await flushPromises()
    expect(wrapper.emitted('progress')).toBeTruthy()
  })

  it('uploads multiple files when multiple files selected', async () => {
    uploadMultipleFilesMock.mockResolvedValue([
      { file: 'a', type: 'excel', success: true, data: {} },
      { file: 'b', type: 'csv', success: true, data: {} },
    ])
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file1 = createFile('a.xlsx')
    const file2 = createFile('b.csv')
    Object.defineProperty(input.element, 'files', { value: [file1, file2], configurable: true })
    await input.trigger('change')
    await flushPromises()
    const uploadBtn = wrapper.findAll('.file-import-footer button')[1]
    await uploadBtn.trigger('click')
    await flushPromises()
    expect(uploadMultipleFilesMock).toHaveBeenCalled()
    expect(wrapper.emitted('uploaded')).toBeTruthy()
  })

  it('emits error when upload throws', async () => {
    uploadFileMock.mockRejectedValue(new Error('upload error'))
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file = createFile('test.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    const uploadBtn = wrapper.findAll('.file-import-footer button')[1]
    await uploadBtn.trigger('click')
    await flushPromises()
    expect(wrapper.emitted('error')).toBeTruthy()
  })

  it('formats file size correctly for bytes', async () => {
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file = createFile('test.xlsx', '', 500)
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.find('.file-size').text()).toContain('B')
  })

  it('formats file size correctly for 0 bytes', async () => {
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file = createFile('test.xlsx', '', 0)
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.find('.file-size').text()).toBe('0 B')
  })

  it('applies dragover class when dragging over', async () => {
    const wrapper = mountFileImport()
    await wrapper.find('.drop-zone').trigger('dragenter', { preventDefault: () => {} })
    expect(wrapper.find('.drop-zone').classes()).toContain('dragover')
  })

  it('removes dragover class on dragleave', async () => {
    const wrapper = mountFileImport()
    await wrapper.find('.drop-zone').trigger('dragenter', { preventDefault: () => {} })
    expect(wrapper.find('.drop-zone').classes()).toContain('dragover')
    await wrapper.find('.drop-zone').trigger('dragleave', {
      preventDefault: () => {},
      relatedTarget: null,
      currentTarget: wrapper.find('.drop-zone').element,
    })
    expect(wrapper.find('.drop-zone').classes()).not.toContain('dragover')
  })

  it('handles drop event with files', async () => {
    const wrapper = mountFileImport()
    const file = createFile('dropped.xlsx')
    const dropEvent = {
      preventDefault: () => {},
      dataTransfer: { files: [file] },
    }
    await wrapper.find('.drop-zone').trigger('drop', dropEvent)
    await flushPromises()
    expect(wrapper.find('.file-list').exists()).toBe(true)
    expect(wrapper.text()).toContain('dropped.xlsx')
  })

  it('does not add files on drop when uploading', async () => {
    uploadingRef.value = true
    const wrapper = mountFileImport()
    const file = createFile('dropped.xlsx')
    const dropEvent = {
      preventDefault: () => {},
      dataTransfer: { files: [file] },
    }
    await wrapper.find('.drop-zone').trigger('drop', dropEvent)
    await flushPromises()
    expect(wrapper.find('.file-list').exists()).toBe(false)
  })

  it('triggers file input click when drop zone is clicked', async () => {
    const wrapper = mountFileImport()
    const clickSpy = vi.spyOn(wrapper.find('.file-input').element as HTMLInputElement, 'click')
    await wrapper.find('.drop-zone').trigger('click')
    expect(clickSpy).toHaveBeenCalled()
    clickSpy.mockRestore()
  })

  it('does not trigger file input click when uploading', async () => {
    uploadingRef.value = true
    const wrapper = mountFileImport()
    const clickSpy = vi.spyOn(wrapper.find('.file-input').element as HTMLInputElement, 'click')
    await wrapper.find('.drop-zone').trigger('click')
    expect(clickSpy).not.toHaveBeenCalled()
    clickSpy.mockRestore()
  })

  it('replaces files when multiple is false', async () => {
    const wrapper = mountFileImport({ multiple: false })
    const input = wrapper.find('.file-input')
    const file1 = createFile('first.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file1], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.findAll('.file-item')).toHaveLength(1)
    const file2 = createFile('second.csv')
    Object.defineProperty(input.element, 'files', { value: [file2], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.findAll('.file-item')).toHaveLength(1)
    expect(wrapper.find('.file-name').text()).toBe('second.csv')
  })

  it('appends files when multiple is true', async () => {
    const wrapper = mountFileImport({ multiple: true })
    const input = wrapper.find('.file-input')
    const file1 = createFile('first.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file1], configurable: true })
    await input.trigger('change')
    await flushPromises()
    const file2 = createFile('second.csv')
    Object.defineProperty(input.element, 'files', { value: [file2], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.findAll('.file-item')).toHaveLength(2)
  })

  it('auto-uploads when autoUpload is true', async () => {
    uploadFileMock.mockResolvedValue({ success: true })
    const wrapper = mountFileImport({ autoUpload: true })
    const input = wrapper.find('.file-input')
    const file = createFile('auto.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(uploadFileMock).toHaveBeenCalled()
  })

  it('resets state when modelValue changes to false', async () => {
    const wrapper = mountFileImport({ modelValue: true })
    const input = wrapper.find('.file-input')
    const file = createFile('test.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.find('.file-list').exists()).toBe(true)
    resetStateMock.mockClear()
    await wrapper.setProps({ modelValue: false })
    expect(resetStateMock).toHaveBeenCalled()
  })

  it('renders progress section when uploading', async () => {
    uploadingRef.value = true
    progressRef.value = 50
    progressTextRef.value = '上传中...'
    const wrapper = mountFileImport()
    expect(wrapper.find('.import-progress').exists()).toBe(true)
    expect(wrapper.find('.progress-percent').text()).toBe('50%')
    expect(wrapper.find('.progress-text').text()).toBe('上传中...')
  })

  it('renders status section when status.show is true', async () => {
    statusReactive.show = true
    statusReactive.type = 'success'
    statusReactive.message = '上传成功'
    const wrapper = mountFileImport()
    expect(wrapper.find('.import-status').exists()).toBe(true)
    expect(wrapper.find('.import-status').classes()).toContain('success')
    expect(wrapper.find('.import-status').text()).toContain('上传成功')
  })

  it('renders error status with error class', async () => {
    statusReactive.show = true
    statusReactive.type = 'error'
    statusReactive.message = '上传失败'
    const wrapper = mountFileImport()
    expect(wrapper.find('.import-status').classes()).toContain('error')
  })

  it('shows uploading state in upload button', async () => {
    uploadingRef.value = true
    const wrapper = mountFileImport()
    const uploadBtn = wrapper.findAll('.file-import-footer button')[1]
    expect(uploadBtn.text()).toContain('上传中')
    expect(uploadBtn.attributes('disabled')).toBeDefined()
  })

  it('disables cancel button when uploading', async () => {
    uploadingRef.value = true
    const wrapper = mountFileImport()
    const cancelBtn = wrapper.findAll('.file-import-footer button')[0]
    expect(cancelBtn.attributes('disabled')).toBeDefined()
  })

  it('hides clear button when uploading', async () => {
    uploadingRef.value = false
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file = createFile('test.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.find('.clear-btn').exists()).toBe(true)
    uploadingRef.value = true
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.clear-btn').exists()).toBe(false)
  })

  it('validates purpose prop with allowed values', () => {
    const validPurposes = ['general', 'product_import', 'customers_import', 'order_parse', 'materials_import']
    validPurposes.forEach((purpose) => {
      const wrapper = mountFileImport({ purpose })
      expect(wrapper.find('.file-import-overlay').exists()).toBe(true)
      wrapper.unmount()
    })
  })

  it('renders file count in file list header', async () => {
    const wrapper = mountFileImport()
    const input = wrapper.find('.file-input')
    const file1 = createFile('a.xlsx')
    const file2 = createFile('b.csv')
    Object.defineProperty(input.element, 'files', { value: [file1, file2], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.find('.file-list-header span').text()).toContain('2')
  })
})
